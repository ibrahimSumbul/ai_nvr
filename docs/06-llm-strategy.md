# 06 — LLM Stratejisi

> ✅ **M3'te uygulandı.** Tır/dorse renk analizi **lokal Ollama vision modeli** (`qwen2.5vl:7b`) ile yapılıyor. Görüntüler tesisten çıkmaz, aylık marjinal LLM maliyeti **$0**. Kod: [`bridge/bridge/llm.py`](../bridge/bridge/llm.py).

## Genel Felsefe

LLM **her şeyin çözümü değil** — sadece Frigate'in yapamadığı, anlam (semantik) gerektiren işlerde kullanılır:

1. **Tır + dorse renk ayrımı** (Frigate "truck" der, rengi/tipi bilemez) — M3'te aktif
2. **Anomali doğrulama** (örn. "bu kişi düşmüş mü?") — M8 planlı
3. **Yetkisiz alan ihlali doğrulaması** (yüz tanıma sonrası) — M8 planlı

Frigate'in yapabildiği işler için **asla** LLM çağrılmaz: kişi/araç/kamyon tespiti, tracking, zone polygon kontrolü. Gerekçe: [`docs/10-why-frigate.md`](10-why-frigate.md).

## Neden Lokal Ollama? (M3 kararı)

Proje M0'da bulut LLM (Claude Haiku) ile tasarlanmıştı; M3'te **lokal Ollama**'ya geçildi. Gerekçe:

| Kriter | Lokal Ollama (seçilen) | Bulut LLM (Haiku vb.) |
|---|---|---|
| **Gizlilik** | ✅ Görüntüler **tesisten çıkmaz** | ❌ Her snapshot dış servise gider |
| **Marjinal maliyet** | ✅ **$0** (sadece elektrik) | ❌ Çağrı başına ücret, aylık fatura |
| **Kota / rate limit** | ✅ Yok — donanım sınırı kadar | ❌ API tier limiti, throttling |
| **İnternet bağımlılığı** | ✅ Tamamen offline çalışır | ❌ Outbound 443 gerekir |
| **Gecikme** | ⚠️ CPU'da ~30 sn (GPU/Apple Silicon hızlı) | ✅ ~1–2 sn |
| **Kurulum** | ⚠️ Host'ta Ollama + model indirme | ✅ Sadece API key |

Endüstriyel CCTV görüntüsü hassas veridir; gizlilik + sıfır marjinal maliyet, bulut gecikme avantajından ağır bastı. Olaylar zaten **olay-tetikli** (sürekli analiz yok) olduğundan ~30 sn gecikme tır renk kaydı için kabul edilebilir — bu bir alarm yolu değil, zenginleştirme.

### Provider-agnostic mimari

Bridge LLM'e **doğrudan HTTP** çağrısı yapar (Frigate genAI yerine) — bu sayede structured JSON output, `llm_usage` maliyet/gecikme logu ve provider değiştirme imkânı elde edilir. [`bridge/bridge/llm.py`](../bridge/bridge/llm.py)'de `LLMClient` Protocol + `build_llm_client` factory tanımlı:

```python
def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "ollama":
        return OllamaClient(settings)
    raise ValueError(
        f"Desteklenmeyen LLM provider: {settings.llm_provider!r} "
        "(şu an sadece 'ollama' destekleniyor; 'anthropic' gelecekte)"
    )
```

> **Not:** Şu an **yalnızca `ollama`** uygulanmıştır. `LLM_PROVIDER=anthropic` bulut hibrit switch altyapısı hazırdır ama implementasyon henüz yoktur (factory `ValueError` yükseltir). `.env`'deki `ANTHROPIC_*` değişkenleri bu gelecek hibrit için ayrılmıştır.

## Model Seçimi

**`qwen2.5vl:7b`** (Qwen2.5-VL 7B, Ollama üzerinden — `.env` `LLM_OLLAMA_MODEL` ile değiştirilebilir)

| Neden | Detay |
|---|---|
| Lokal vizyon | Görüntü tabanlı analiz, host'ta koşar |
| Yapısal çıktı | Ollama `format=json` ile güvenilir JSON |
| Boyut/kalite dengesi | ~5.6 GB disk, ~6 GB RAM; renk/tip ayrımı için yeterli |
| $0 marjinal | Çalışma maliyeti sadece elektrik |

Host'ta kurulum: `ollama pull qwen2.5vl:7b`. Container modele `host.docker.internal:11434` üzerinden erişir (bkz. [`docs/03-setup.md`](03-setup.md)). Daha büyük/küçük model (örn. `qwen2.5vl:3b` daha hızlı, `:32b` daha kaliteli) `.env` ile seçilebilir.

## Tır + Dorse Renk Analizi (M3 — aktif)

### Çağrı yapısı

[`OllamaClient.analyze_truck`](../bridge/bridge/llm.py) `POST /api/generate` ile çağırır:

```python
payload = {
    "model": settings.llm_ollama_model,          # qwen2.5vl:7b
    "prompt": "Bu kamyonu analiz et ve JSON döndür.",
    "system": TRUCK_PROMPT_SYSTEM,                # aşağıda
    "images": [image_b64],                        # 480px snapshot, base64
    "format": "json",                             # structured output zorunlu
    "stream": False,
    "options": {
        "temperature": 0.1,    # düşük → tutarlı sonuçlar
        "num_predict": 256,    # JSON kısa; 256 yeterli, latency'yi düşürür
    },
}
```

### Sistem prompt'u (gerçek kod)

`TRUCK_PROMPT_SYSTEM` ([`bridge/bridge/llm.py`](../bridge/bridge/llm.py)):

```text
Sen bir araç görüntü analiz asistanısın. Sana endüstriyel tesise giren bir
kamyonun görüntüsü verilecek. Aşağıdakileri tespit edip JSON döndüreceksin.

ÖNEMLİ:
- Sadece JSON döndür, başka açıklama yapma.
- Plaka okumaya çalışma, sadece renk ve genel bilgi.
- RENK ZORUNLU: çekici/dorse rengini gördüğün baskın renge göre MUTLAKA listeden seç.
  Gümüş veya parlak gri araçlar → "metalik" (mat gri ise "gri").
  Açık/kirli beyaz → "beyaz". Koyu lacivert/siyah ayrımında emin değilsen "siyah".
- "bilinmeyen" rengi SADECE araç gölgede/bulanık olup renk gerçekten seçilemiyorsa kullan.
  Rengi görebiliyorsan "bilinmeyen" DEME — en yakın rengi seç ve "guven"i ona göre ayarla.
- "guven": tahminin netliği (0.0-1.0). Renk nettse yüksek, belirsizse düşük.
- "notlar": KISA tut, en fazla 1 kısa cümle (uzun metin çıktıyı bozar).
- Renk listesi: beyaz, siyah, gri, kirmizi, mavi, yesil, sari, turuncu, kahverengi,
  mor, pembe, lacivert, krem, bordo, metalik, bilinmeyen

Şema:
{
  "tir_var_mi": boolean,
  "cekici_rengi": <renk> | null,
  "dorse_var_mi": boolean,
  "dorse_rengi": <renk> | null,
  "dorse_tipi": "tenteli" | "frigo" | "konteyner" | "acik" | "tanker" | "bilinmeyen" | null,
  "yon": "giris" | "cikis" | "duruyor" | "bilinmeyen" | null,
  "guven": float (0.0-1.0),
  "notlar": string | null
}
```

> **Renk prompt'u M3 kalite tuning'i** (smoke test sonrası): Model rengi görse bile "bilinmeyen" döndürme eğilimindeydi. Prompt enum'a commit etmeye zorlandı (gümüş→metalik, açık→beyaz kuralları), böylece siyah/gri gibi renkler doğru çıkmaya başladı. Bkz. [`CHANGELOG.md`](../CHANGELOG.md) "M3 — LLM kalite tuning".

### Çıktı doğrulama (Pydantic)

Ollama yanıtı `TruckAnalysis.model_validate_json(raw)` ile parse + valide edilir. Enum dışı bir değer gelirse `ValueError` → retry tetiklenir.

```python
Color = Literal["beyaz", "siyah", "gri", "kirmizi", "mavi", "yesil", "sari",
    "turuncu", "kahverengi", "mor", "pembe", "lacivert", "krem", "bordo",
    "metalik", "bilinmeyen"]                       # 16 renk
TrailerType = Literal["tenteli", "frigo", "konteyner", "acik", "tanker", "bilinmeyen"]
Direction = Literal["giris", "cikis", "duruyor", "bilinmeyen"]

class TruckAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")      # fazladan alan tolere edilir
    tir_var_mi: bool
    cekici_rengi: Color | None = None
    dorse_var_mi: bool
    dorse_rengi: Color | None = None
    dorse_tipi: TrailerType | None = None
    yon: Direction | None = None
    guven: float = Field(ge=0.0, le=1.0)
    notlar: str | None = None
```

`guven` alanı tahminin netliğini taşır; Grafana'da düşük güvenli sonuçlar filtrelenebilir / insan incelemesine işaretlenebilir.

### Snapshot downscale (latency kontrolü)

LLM'e gönderilen görüntü Frigate'in server-side resize'ı ile küçültülür (`?height=N`). `LLM_SNAPSHOT_MAX_HEIGHT=480` varsayılan:

> **M3 ölçüm**: 800px → **121 sn**, 480px → **33 sn** (CPU inference, %73↓). Renk analizi için 480px yeterli. Bkz. [`CHANGELOG.md`](../CHANGELOG.md).

## Truck event akışı (uçtan uca)

[`bridge/bridge/trucks.py`](../bridge/bridge/trucks.py) `TruckEventHandler`:

1. Frigate event'inde `label == "truck"` **ve** `score >= LLM_TRUCK_MIN_SCORE` (0.6). Altındaysa LLM çağrılmaz (`truck.skipped_low_score`).
2. **Dedup**: aynı `frigate_event_id` daha önce işlendiyse atla (memory cache + DB `truck_event_exists`).
3. Snapshot fetch (`height=480`).
4. `OllamaClient.analyze_truck` → `TruckAnalysis`.
5. `llm_usage` insert (önce — `truck_events` FK referans alır), sonra `truck_events` insert.
6. **Hata**: `LLMError` → `llm_usage`'a `success=False` + `error` yazılır, `truck_events` boş bırakılır. Zone/Dahua akışı etkilenmez.

## Maliyet & İzleme

### Marjinal maliyet: $0

Lokal Ollama'da her çağrı `cost_usd = 0.0` olarak loglanır (sadece elektrik tüketimi). Bulut LLM'in çağrı-başı ücreti, aylık fatura ve kota baskısı **yoktur**. Detaylı kıyaslama: [`docs/07-cost-analysis.md`](07-cost-analysis.md).

### `llm_usage` tablosu (gerçek şema)

Her LLM çağrısı — başarılı veya başarısız — loglanır:

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  call_type TEXT NOT NULL,         -- 'truck_color' | 'anomaly' | 'unauthorized'
  model TEXT NOT NULL,             -- 'qwen2.5vl:7b'
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  cached_input_tokens INT NOT NULL DEFAULT 0,
  cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,   -- Ollama'da 0
  latency_ms INT,
  success BOOLEAN NOT NULL DEFAULT TRUE,
  error TEXT,
  metadata JSONB DEFAULT '{}'::jsonb           -- {"frigate_event_id": ...}
);
```

Grafana "AI NVR — Genel Bakış" dashboard'u bu tablodan **LLM başarı oranı** ve **gecikme (timeseries)** panellerini çizer. Maliyet kolonu lokal kullanımda sıfırdır; planlı bulut hibritte dolar.

### Bütçe guard (yalnızca bulut hibritte)

`LLM_MONTHLY_BUDGET_USD` (default 10) ve bütçe kontrolü **yalnızca opsiyonel bulut hibrit** (`LLM_PROVIDER=anthropic`, planlı) kullanılırsa anlamlıdır. Lokal Ollama'da bütçe sınırı yoktur; sınır donanım throughput'udur (CPU'da ~30 sn/çağrı → olay-tetikli kullanım zaten bunu doğal sınırlar).

## Hata ve Retry

[`OllamaClient`](../bridge/bridge/llm.py) davranışı:

- **Timeout**: `LLM_TIMEOUT_S=90` sn. CPU inference yavaş; soğuk çağrı + vision encode 60 sn'i aşabilir, 90 sn güvenli marj. GPU/Coral sonrası düşürülebilir.
- **Retry**: `LLM_MAX_RETRIES=2` (toplam 3 deneme). HTTP hatası veya JSON parse hatası (`ValueError`) retry'a girer.
- Tüm denemeler başarısızsa `LLMError` yükselir → handler `llm_usage.success=false` yazar, event düşmez.

## Anomali Doğrulama (M8 planlı)

Frigate şüpheli hareket pattern'i (hızlı düşüş, uzun sabit duruş) yakaladığında bridge görüntüyü **aynı lokal Ollama**'ya ikinci bir prompt ile gönderebilir:

```text
[image]
Bu görüntüde aşağıdakilerden biri var mı? JSON döndür:
{ "dusus": bool, "kavga": bool, "tirmanma": bool,
  "saglik_problemi": bool, "guven": float, "aciklama": string }
```

`call_type="anomaly"` olarak loglanır. M3'te pasif; M8'de Dahua alarm tetiklemeye bağlanır.

## Test Set

Pilot fazda her tipte örnek görüntü:
- Tır + dorse (5 farklı renk kombinasyonu)
- Gece görüntüsü (IR mode), yağmurlu/sisli
- Multiple araç aynı karede

Hedef: %90+ doğru renk ataması. Birim testleri: [`bridge/tests/test_llm.py`](../bridge/tests) (Pydantic parsing, geçersiz renk/tip/guven, JSON string parse) + `test_trucks.py` (success path, low score, dedup, no_snapshot, LLM failure).

## İleride

- **Bulut hibrit fallback** (planlı): `LLM_PROVIDER=anthropic` — lokal Ollama yavaş/yetersizse veya daha yüksek kalite gerekirse opsiyonel olarak Haiku'ya yönlendirme. Provider-agnostic interface bunu drop-in yapar; sadece `AnthropicClient` implementasyonu eklenecek.
- **Daha hızlı inference**: GPU veya Apple Silicon host ile ~30 sn → birkaç saniye.
- **Embedding tabanlı snapshot araması**: "kırmızı dorseli tırları göster" gibi semantik sorgular.
