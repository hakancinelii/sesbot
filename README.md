# Sesbot — Kitap Seslendirme Botu

[VoxCPM Demo](https://huggingface.co/spaces/openbmb/VoxCPM-Demo) sitesini kullanarak PDF kitabı paragraf paragraf seslendirir.

## Kurulum

```bash
pip3 install -r requirements.txt
```

## Kullanım

Önce tek sayfa ile test edin:

```bash
python3 sesbot.py --start-page 24 --end-page 24
```

Tüm kitap için:

```bash
python3 sesbot.py --start-page 10
```

Paragrafları listelemek (ses üretmeden):

```bash
python3 sesbot.py --list-only --start-page 24 --end-page 24
```

## Çıktı

Ses dosyaları `output/` klasörüne kaydedilir:

```
output/
  24_1.mp3   # 24. sayfa, 1. paragraf
  24_2.mp3   # 24. sayfa, 2. paragraf
  24.mp3     # 24. sayfanin birlestirilmis hali
  ...
  progress.json
```

Her sayfa tamamlandiginda paragraflar ayrica `24.mp3` gibi tek dosyada birlestirilir. Paragraflar arasina varsayilan **1.5 saniye** duraksama eklenir.

Paragraf dosyalari zaten varken sadece birlestirmek icin:

```bash
python3 sesbot.py --merge-only --start-page 24 --end-page 25 --force-merge
```

Duraksama suresini ayarlamak icin (ornegin 2 saniye):

```bash
python3 sesbot.py --pause-ms 2000 --start-page 24 --end-page 24
```

Duraksama istemiyorsaniz:

```bash
python3 sesbot.py --pause-ms 0 --merge-only --start-page 24 --end-page 24 --force-merge
```

Not: Duraksama icin `imageio-ffmpeg` paketi otomatik ffmpeg saglar. Alternatif: `brew install ffmpeg`

## Parametreler

| Parametre | Varsayılan | Açıklama |
|-----------|------------|----------|
| `--pdf` | `Dan-Brown-Sirlarin-Sirri.pdf` | Kitap PDF'i |
| `--reference` | `amazon_reference_50s.mp3` | Klonlanacak referans ses |
| `--output` | `output` | Çıktı klasörü |
| `--start-page` | `10` | Başlangıç sayfa numarası |
| `--end-page` | (son) | Bitiş sayfa numarası |
| `--cfg` | `2.0` | CFG guidance scale |
| `--delay` | `3.0` | İstekler arası bekleme (sn) |
| `--pause-ms` | `1500` | Paragraflar arası duraksama (ms), 1.5 sn |
| `--force-merge` | kapalı | Birleşik sayfa dosyalarını yeniden oluştur |
| `--merge-only` | kapalı | Mevcut paragrafları sayfa bazında birleştir |
| `--no-merge` | kapalı | Sayfa birleştirme dosyası oluşturma |

Paragraflar arasında nefes payı için `--pause-ms` kullanılır. Örnek: `2000` = 2 saniye duraklama.

Mevcut sayfaları duraklamayla yeniden birleştirmek için:

```bash
python3 sesbot.py --merge-only --start-page 24 --end-page 25 --pause-ms 1500 --force-merge
```

## Ultimate Cloning Mode nedir?

Sizin kullandığınız mod **Controllable Cloning** (kontrollü klonlama):

- Referans ses yüklenir
- İsteğe bağlı Control Instruction ile ton/hız ayarlanır
- Model referans sesin **tınısını** kopyalar

**Ultimate Cloning Mode** farklı çalışır:

- Referans sesin **yazılı transkripti** gerekir (ASR ile otomatik doldurulabilir)
- Model, referans sesi konuşmanın **başlangıcı** gibi görür ve metni **devam ettirerek** üretir
- Control Instruction devre dışı kalır
- Daha yüksek sadakat sağlar ama referans sesin içeriği hedef metinle uyumlu olmalıdır

Kitap seslendirme için referans sesiniz sabit bir örnek olduğundan **Controllable Cloning** (Ultimate kapalı) doğru seçimdir.

## Sesli okuyucu arayuzu

Metni takip ederek dinlemek icin yerel okuyucuyu acin:

```bash
python3 reader_server.py
```

Tarayicida `http://127.0.0.1:8765` acilir.

- Paragrafa tiklayinca o paragraf calar ve vurgulanir
- Paragraf bitince otomatik sonraki paragrafa gecer
- `Space` = oynat/duraklat, ok tuslari = paragraf degistir
- "Tum sayfa sesi" secenegi birlesik `24.mp3` gibi dosyayi calar

## Vercel'de canli okuyucu

Canli adres: **https://sesbot-okuyucu.vercel.app**

Yeni ses dosyalari uretildikten sonra yeniden yayinlamak icin:

```bash
python3 scripts/build_vercel.py
cd public
npx vercel deploy --prod --yes
```

Veya token ile:

```bash
export VERCEL_TOKEN="vercel_tokeniniz"
python3 scripts/deploy_vercel.sh
```

**Guvenlik:** Vercel token'inizi kimseyle paylasmayin ve sohbette paylastiysaniz Vercel panelinden yenileyin.

