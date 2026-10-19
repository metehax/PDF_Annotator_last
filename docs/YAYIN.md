# Yayın adımları (GitHub)

1. `appinfo.py` → `VERSION` değerini artır (ör. `1.0.1`). `UPDATE_URL` bir kez ayarlanır:
   `https://api.github.com/repos/<sahip>/<depo>/releases/latest` (herkese açık depo; özel depoda kimlik doğrulamasız çalışmaz)
   ya da `https://github.com/<sahip>/<depo>/releases/latest/download/latest.json`.
2. `build.bat` → `dist\PDF-Annotator-Setup-<sürüm>.exe` (+ SHA-256 yazdırır).
3. `python tools\make_release.py --notes notlar.md` → `dist\latest.json` ve `.sha256`.
4. GitHub'da **yeni Release** aç: etiket `v<sürüm>`; kurucuyu, `latest.json`'u ve `.sha256` dosyasını yükle; notları açıklamaya yaz.
5. Çalışan sürümler Release'i (açılışta ya da Yardım → Güncellemeleri denetle) bulur, notları gösterir, SHA-256'yı doğrulayıp kurar.

Güvenlik: yalnızca HTTPS; SHA-256 eşleşmezse indirilen dosya silinir. Kurucu imzalı değilse SmartScreen uyarısı çıkar (README).
