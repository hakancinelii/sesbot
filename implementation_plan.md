# Sesbot İyileştirmeleri ve Dinamik Seslendirme

Bu plan, arayüzdeki karakter bozukluklarını gidermeyi ve eksik paragrafların arayüz üzerinden dinamik olarak seslendirilmesini sağlamayı amaçlamaktadır.

## User Review Required

Vercel üzerinde dinamik seslendirme yapabilmek için bir `/api/generate` endpoint'i ekleyeceğiz. VoxCPM'in ses üretmesi bazen uzun sürebilmektedir. Vercel tarafında (eğer Hobby planındaysanız) 10 saniye timeout limiti olabilir. Limit sorununun çözüldüğünü belirttiniz, bu nedenle Serverless Function'ın çalışacağını öngörüyoruz.

Arayüzde üretilen ses geçici olarak tarayıcıda çalınacaktır. Kalıcı olarak dosyaya kaydetmek Vercel'in read-only dosya sistemi nedeniyle doğrudan mümkün değildir (bunun için harici bir storage gerekir). Bu aşamada sesi anlık üretip çalacak şekilde tasarlayacağız.

## Proposed Changes

### `sesbot.py`
- PDF'ten metin çıkarılırken oluşan font bazlı karakter bozulmalarını (örn. `ᮡ` -> `A`, `ᰅ` -> `a`) düzelten kapsamlı bir karakter haritası ve `clean_text` fonksiyonu eklenecektir.

### `reader/app.js` & `reader/index.html` & `reader/style.css`
- Ses olmayan paragraflar için arayüze "Seslendir" (Generate) butonu eklenecektir.
- Butona tıklandığında `/api/generate` endpoint'ine istek atıp dönen sesi çalacak (ve UI'da yükleniyor animasyonu gösterecek) mantık eklenecektir.

### `api/generate.py` (YENİ - Vercel için)
- Vercel Serverless Function olarak çalışacak bu Python betiği, gelen metni alıp HuggingFace VoxCPM API'sine iletecek ve üretilen sesi döndürecektir.
- Referans ses (`amazon_reference_50s.mp3`) base64 veya kalıcı bir URL üzerinden kullanılacaktır.

### `reader_server.py`
- Yerel sunucunun da arayüzdeki "Seslendir" butonunu desteklemesi için `/api/generate` route'u eklenecek ve yerel olarak ses üretip döndürmesi sağlanacaktır.

## Verification Plan

- `sesbot.py` test edilerek 27. sayfadaki "ᮡçık konuşayım" gibi metinlerin "Açık konuşayım" olarak düzgün çıkarıldığı doğrulanacak.
- Yerel sunucu (`reader_server.py`) başlatılıp arayüzde eksik bir paragrafın "Seslendir" butonuna basılarak sesin başarılı bir şekilde üretilip çalındığı test edilecek.
- Vercel'e deploy alınarak canlı ortamda da dinamik seslendirmenin çalıştığı doğrulanacak.
