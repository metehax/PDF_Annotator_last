"""Dijital imza (pyhanko): .pfx/.p12 ile PAdES imzalama, imza doğrulama ve
imzadan sonra yapılan değişikliklerin denetimi."""
import datetime as _dt
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

# kendinden imzalı sertifika vb. için pyhanko konsola iz basmasın; sonuç raporda
logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)

MOD_TEXT = {
    "NONE": "Değişiklik yok",
    "LTA_UPDATES": "Yalnızca zaman damgası/doğrulama verisi eklenmiş",
    "FORM_FILLING": "İmzadan sonra form doldurulmuş",
    "ANNOTATIONS": "İmzadan sonra açıklama/işaret eklenmiş",
    "OTHER": "İmzadan sonra içerik DEĞİŞTİRİLMİŞ",
}


def load_signer(pfx_path: str, password: str) -> signers.SimpleSigner:
    s = signers.SimpleSigner.load_pkcs12(pfx_path, passphrase=password.encode("utf-8") if password else None)
    if s is None:
        raise ValueError("Sertifika açılamadı: parola yanlış ya da dosya geçersiz.")
    return s


def signer_name(signer) -> str:
    try:
        return signer.signing_cert.subject.native.get("common_name") or signer.signing_cert.subject.human_friendly
    except Exception:
        return "?"


def empty_signature_fields(path: str) -> List[str]:
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        return [name for name, value, _ref in fields.enumerate_sig_fields(r) if value is None]


def sign_pdf(src: str, out: str, pfx: str, password: str, field: Optional[str] = None,
             new_box: Optional[Tuple[int, Tuple[float, float, float, float]]] = None,
             reason: str = "", location: str = "") -> str:
    """src'yi artımlı olarak imzalayıp out'a yazar. field: mevcut boş alan adı;
    new_box: (sayfa, (x0, y0, x1, y1) sol-üst kökenli pt) görünür yeni alan;
    ikisi de yoksa görünmez imza. İmzalayanın adını döner."""
    signer = load_signer(pfx, password)
    with open(src, "rb") as f:
        w = IncrementalPdfFileWriter(f, strict=False)
        if not field:
            field = _unique_field(w)
            if new_box is not None:
                pidx, (x0, y0, x1, y1) = new_box
                h = _page_height(src, pidx)
                spec = fields.SigFieldSpec(field, on_page=pidx, box=(x0, h - y1, x1, h - y0))
            else:
                spec = fields.SigFieldSpec(field)
            fields.append_signature_field(w, spec)
        meta = signers.PdfSignatureMetadata(field_name=field, reason=reason or None,
                                            location=location or None, md_algorithm="sha256")
        with open(out, "wb") as o:
            signers.PdfSigner(meta, signer=signer).sign_pdf(w, output=o)
    return signer_name(signer)


def _page_height(path: str, pidx: int) -> float:
    import fitz
    with fitz.open(path) as d:
        return float(d[pidx].mediabox.height)


def _unique_field(w) -> str:
    names = {n for n, _v, _r in fields.enumerate_sig_fields(w)}
    i = 1
    while f"Imza{i}" in names:
        i += 1
    return f"Imza{i}"


@dataclass
class SigReport:
    field: str
    signer: str
    when: str
    intact: bool          # imzalanan bayt aralığı bozulmamış
    valid: bool           # kriptografik olarak geçerli
    trusted: bool         # sertifika zinciri güvenilir köke bağlı
    covers_all: bool      # imza dosyanın tamamını kapsıyor (sonradan revizyon yok)
    modification: str     # MOD_TEXT anahtarı
    reason: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.intact and self.valid and self.modification in ("NONE", "LTA_UPDATES")


def verify_pdf(path: str) -> List[SigReport]:
    out = []
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        for emb in r.embedded_signatures:
            try:
                st = validate_pdf_signature(emb, ValidationContext(allow_fetching=False))
                ml = getattr(st, "modification_level", None)
                cov = getattr(st, "coverage", None)
                dt = st.signer_reported_dt or getattr(emb, "self_reported_timestamp", None)
                out.append(SigReport(
                    field=emb.field_name, signer=signer_name(type("S", (), {"signing_cert": st.signing_cert})),
                    when=dt.astimezone().strftime("%d.%m.%Y %H:%M") if isinstance(dt, _dt.datetime) else "",
                    intact=bool(st.intact), valid=bool(st.valid), trusted=bool(st.trusted),
                    covers_all=bool(cov is not None and cov.name == "ENTIRE_FILE"),
                    modification=ml.name if ml is not None else ("NONE" if cov and cov.name == "ENTIRE_FILE"
                                                                 else "OTHER"),
                    reason=str(emb.sig_object.get("/Reason", "") or "")))
            except Exception as ex:
                out.append(SigReport(emb.field_name, "?", "", False, False, False, False, "OTHER",
                                     error=str(ex)))
    return out


def create_self_signed(path: str, name: str, password: str, days: int = 1095) -> None:
    """Deneme/kurum içi kullanım için kendinden imzalı .pfx üretir."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=days))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
            .sign(key, hashes.SHA256()))
    enc = (serialization.BestAvailableEncryption(password.encode("utf-8")) if password
           else serialization.NoEncryption())
    with open(path, "wb") as f:
        f.write(pkcs12.serialize_key_and_certificates(name.encode("utf-8"), key, cert, None, enc))
