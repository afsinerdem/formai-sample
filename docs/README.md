# FormAI Dokümantasyon İndeksi

Bu klasör, FormAI'nin ürün amacı, teknik mimarisi, kalite resmi, API yüzeyi, web katmanı ve release/arşiv politikası için ana bilgi kaynağıdır.

## Okuma Sırası

1. [Genel Bakış](overview.md)
2. [Ürün Vizyonu](product/vision.md)
3. [Sistem Mimarisi](architecture/system-overview.md)
4. [Repo Layout](architecture/repo-layout.md)
5. [Statik PDF -> AcroForm Pipeline](architecture/pdf-pipeline.md)
6. [Güncel Kalite Durumu](quality/current-state.md)
7. [Dataset ve Benchmark Mantığı](quality/datasets-and-benchmarks.md)
8. [API ve Job Modeli](api-and-jobs.md)
9. [Web Katmanı](web/overview.md)
10. [Release ve Arşiv Politikası](operations/release-and-archive.md)
11. [0.2.0 Release Manifest](releases/0.2.0/manifest.md)

## Kısa Tanım

FormAI, bir kurumdaki form akışını yeniden platformlaştırmadan iyileştirmeyi hedefler.

Girdi olarak iki şey kabul eder:
- boş, statik veya kısmen yapılandırılmış PDF form şablonu
- dolu PDF veya dolu form görseli

Çıktı olarak üç şey üretir:
- doldurulabilir `AcroForm` PDF
- yapılandırılmış veri
- kullanıcıya gösterilebilecek final PDF

## Bugünkü Gerçeklik

- Sistem modüler ve testli.
- Local-first çalışma yolu var.
- Benchmark ve verification katmanı mevcut.
- API ve workbench yüzeyi hazır.
- En kritik açık alan hâlâ coordinate/placement doğruluğu ve özellikle zor Türkçe gerçek form ailelerinde visual güvenilirlik.

Detay için [Güncel Kalite Durumu](quality/current-state.md) belgesine bak.
