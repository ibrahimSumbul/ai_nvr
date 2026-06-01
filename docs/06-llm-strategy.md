# 06 — LLM Stratejisi

> **M3'te uygulandı (lokal Ollama).** Bu doküman gerçek koda (`bridge/bridge/llm.py`) göre hizalanmıştır: provider **lokal Ollama** (`qwen2.5vl:7b`), `POST /api/generate` + `format=json` structured output. Aylık maliyet **$0** (sadece elektrik), görüntüler tesisten çıkmaz. Bulut hibrit (Anthropic) **planlıdır** — `LLM_PROVIDER` switch + factory hazır, ama `AnthropicClient` henüz yazılmadı; `build_llm_client` `ollama` dışında provider'a `ValueError` verir.

## Genel Felsefe

LLM **doğru yerde kullanılırsa değerlidir.** Lokal Ollama'da çağrı başına para maliyeti yoktur ($0), ama her çağrı CPU/inference zamanı tüketir; bu yüzden LLM yine **sadece** şu işler için, **olay-tetikli** çağrılır:

1. **Tır + dorse renk ayrımı** (Frigate yapamaz) — M3'te aktif
2. **Anomali doğrulama** (örn. "bu kişi düşmüş mü?") — planlı
3. **Yetkisiz alan ihlali doğrulaması** (M8'de, yüz tanıma ekledikten sonra) — planlı

Frigate'in yapabildiği işler için **asla** LLM çağrılmaz: kişi tespiti, araç tespiti, basit hareket. Ayrıca Frigate truck label skoru `LLM_TRUCK_MIN_SCORE` (varsayılan 0.6) altındaysa LLM hiç çağrılmaz.

## Model Seçimi

**Lokal Ollama vision modeli — `qwen2.5vl:7b`** (`.env` `LLM_OLLAMA_MODEL` ile değiştirilebilir)

| Neden | Detay |
|---|---|
| Maliyet $0 | Lokal inference, token ücreti yok — sadece elektrik |
| Gizlilik | Görüntüler host'tan/tesisten çıkmaz (KVKK/GDPR dostu) |
| Vizyon destekler | Görüntü tabanlı analiz (vision-language model) |
| Yapısal çıktı | Ollama `format=json` ile JSON döndürme güvenilir |
| Kota yok | API rate-limit yok; sınır yalnızca host inference kapasitesi |

Trade-off: GPU'suz CPU inference **yavaştır** (saniyeler; `LLM_TIMEOUT_S` varsayılan 90s soğuk/büyük görüntü için marj). Olay-tetikli kullanımda kabul edilebilir.

Alternatifler / **planlı** bulut hibrit:
- **Anthropic Claude (Haiku sınıfı)**: bulut, hızlı, güçlü vizyon — ama token maliyeti + görüntü dışarı çıkar + kota. `LLM_PROVIDER=anthropic` switch'i ve `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` ayarları kodda **rezerve** ama `AnthropicClient` henüz yok (planlı fallback).
- Daha büyük lokal model (örn. `qwen2.5vl:32b`) kalite için, ama daha çok RAM/VRAM ister.

## Ollama Çağrı Mekaniği (gerçek)

Bridge Anthropic SDK kullanmaz; doğrudan Ollama HTTP API'ye gider (`OllamaClient`, `httpx.AsyncClient`). Anthropic'e özgü prompt caching (`cache_control`) **yoktur**; Ollama modeli bellekte tuttuğu için (`keep_alive`) tekrar çağrılar zaten hızlanır.

```python
# bridge/bridge/llm.py — OllamaClient.analyze_truck (özet)
payload = {
    "model": settings.llm_ollama_model,          # qwen2.5vl:7b
    "prompt": "Bu kamyonu analiz et ve JSON döndür.",
    "system": TRUCK_PROMPT_SYSTEM,                 # aşağıdaki sistem prompt
    "images": [image_b64],                         # snapshot, ≤480px downscale
    "format": "json",                              # structured JSON output
    "stream": False,
    "options": {
        "temperature": 0.1,                        # düşük → tutarlı sonuç
        "num_predict": 256,                        # JSON kısa; latency'yi sınırlar
    },
}
# POST /api/generate → response.json()["response"] → TruckAnalysis.model_validate_json(...)
```

## Prompt 1: Tır + Dorse Renk Analizi

### Sistem Prompt (`TRUCK_PROMPT_SYSTEM`, gerçek)

Aşağıdaki, `bridge/bridge/llm.py` içindeki gerçek sistem prompt'tur. Renk seçimini zorunlu kılan ve "bilinmeyen"i sınırlayan kurallar M3 kalite tuning'i (renk prompt fix) ile eklendi:

```text
Sen bir araç görüntü analiz asistanısın. Sana endüstriyel tesise giren bir kamyonun görüntüsü verilecek. Aşağıdakileri tespit edip JSON döndüreceksin.

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
- Renk listesi: beyaz, siyah, gri, kirmizi, mavi, yesil, sari, turuncu, kahverengi, mor, pembe, lacivert, krem, bordo, metalik, bilinmeyen

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

### Kullanıcı mesajı

```text
[image]  (snapshot, server-side ≤480px downscale)
Bu kamyonu analiz et ve JSON döndür.
```

### Çıktı doğrulama (Pydantic — gerçek `TruckAnalysis`)

Renk ve dorse tipi serbest string değil, **Literal enum**'dur; Ollama listede olmayan bir değer döndürürse `model_validate_json` başarısız olur ve retry tetiklenir.

```python
Color = Literal[
    "beyaz", "siyah", "gri", "kirmizi", "mavi", "yesil", "sari", "turuncu",
    "kahverengi", "mor", "pembe", "lacivert", "krem", "bordo", "metalik", "bilinmeyen",
]
TrailerType = Literal["tenteli", "frigo", "konteyner", "acik", "tanker", "bilinmeyen"]
Direction = Literal["giris", "cikis", "duruyor", "bilinmeyen"]

class TruckAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tir_var_mi: bool
    cekici_rengi: Color | None = None
    dorse_var_mi: bool
    dorse_rengi: Color | None = None
    dorse_tipi: TrailerType | None = None
    yon: Direction | None = None
    guven: float = Field(ge=0.0, le=1.0)
    notlar: str | None = None
```

> Düşük `guven`li sonuçlar DB'ye yine yazılır (event log her zaman insert edilir); operasyonel tarafta düşük güven Grafana'dan izlenebilir.

## Prompt 2: Anomali Doğrulama (planlı)

Frigate "person" tespit etti, hareket pattern'i şüpheli (örn. çok hızlı düşüş, çok uzun süre sabit duruş). Bridge bunu opsiyonel olarak lokal Ollama'ya doğrulatır (M3'te uygulanmadı; planlı).

```text
[image]
Bu görüntüde aşağıdakilerden biri var mı?
JSON döndür: {
  "dusus": bool,
  "kavga": bool,
  "tirmanma": bool,
  "saglik_problemi": bool,
  "guven": float,
  "aciklama": string
}
```

> M3 milestone'da bu pasif (sadece log). M7'de Dahua alarm tetiklenmeye başlar.

## Maliyet ve Gecikme Kontrolü (Lokal Ollama)

### Per-çağrı

Lokal Ollama'da çağrı başına **para maliyeti $0**'dır; ölçülen büyüklük token-doları değil **gecikme**dir. Bridge yine de token sayımını ve gecikmeyi `llm_usage`'a yazar (`cost_usd` Ollama'da 0).

| Bileşen | Token (tahmini) | Para | Not |
|---|---|---|---|
| Sistem prompt (`TRUCK_PROMPT_SYSTEM`) | ~400 | $0 | Her çağrıda `system` alanında |
| Görüntü (snapshot, ≤480px) | ~300–500 | $0 | `LLM_SNAPSHOT_MAX_HEIGHT=480` |
| User msg | ~10 | $0 | "Bu kamyonu analiz et ve JSON döndür." |
| Output JSON | ≤256 | $0 | `num_predict=256` |
| **Per çağrı** | | **$0** | Gecikme: CPU'da saniyeler |

### Aylık tahmin

| Olay | Çağrı/ay | Para |
|---|---|---|
| Tır renk (20/gün × 30) | 600 | $0 |
| Anomali doğrulama (planlı) | 300 | $0 |
| Yetkisiz alan (M8+, planlı) | 150 | $0 |
| **Toplam aylık** | **~1.050** | **$0** |

### Çağrı Sıklığı Kontrolü (para değil, kuyruk)

Lokal Ollama'da bütçe-kesme yerine **gereksiz çağrıyı önlemek** asıl mekanizmadır:
- `LLM_TRUCK_MIN_SCORE` (varsayılan 0.6): Frigate truck skoru bunun altındaysa LLM hiç çağrılmaz.
- `LLM_SNAPSHOT_MAX_HEIGHT` (480): büyük kaynak görüntüde latency'yi sınırlar.
- Aynı olay için tekrar analiz yapılmaz (idempotent truck event akışı).

> `.env` `LLM_MONTHLY_BUDGET_USD` ayarı kodda durur ama yalnızca **planlı** Anthropic hibriti içindir; lokal Ollama'da $0 olduğu için bir bütçe-kesme tetiklenmez.

`llm_usage` tablosu (token + gecikme metadata'sı; `cost_usd` Ollama'da 0):

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  call_type TEXT,           -- 'truck_color' | 'anomaly' | ...
  model TEXT,               -- 'qwen2.5vl:7b'
  input_tokens INT,         -- Ollama prompt_eval_count
  output_tokens INT,        -- Ollama eval_count
  cached_tokens INT,        -- Ollama'da 0
  cost_usd NUMERIC(10,6),   -- Ollama'da 0 (electric)
  latency_ms INT,
  success BOOLEAN,
  error TEXT
);
```

## Hata ve Retry (gerçek)

`OllamaClient` kendi retry'ını yapar (Anthropic SDK yok):

- **Timeout**: `LLM_TIMEOUT_S` varsayılan **90 sn** (CPU inference + vision encode soğukta uzayabilir; GPU/Coral sonrası düşürülebilir).
- **Retry**: `LLM_MAX_RETRIES` varsayılan **2** ek deneme. `httpx.HTTPError` veya JSON parse (`ValueError`) yakalanır, `llm.attempt_failed` log'lanır.
- Tüm denemeler başarısızsa `LLMError` fırlatılır; tır analizi atlanır ama **zone olayı/alarm yine işlenir** (LLM kritik yol değil).
- Ollama host'ta kapalıysa: bağlantı hatası → retry → `LLMError`. Host'ta `ollama serve` ve model yüklü olmalı.

## Test Set

Pilot fazda her tipte 20 görüntü:
- Tır + dorse (5 farklı renk kombinasyonu)
- Plaka okunamayan zor açı
- Gece görüntüsü (IR mode)
- Yağmurlu/sisli
- Multiple araç aynı karede

Beklenen başarı: %90+ doğru renk ataması.

## İleride

- **Bulut hibrit (planlı)**: `LLM_PROVIDER=anthropic` + `AnthropicClient` — lokal Ollama yetmediğinde (örn. çok zor görüntü, daha yüksek kalite ihtiyacı) bulut fallback. Switch + factory + `ANTHROPIC_*` ayarları hazır, implementasyon henüz yok.
- **Daha büyük lokal model**: kalite için `qwen2.5vl:32b` gibi (daha çok RAM/VRAM gerektirir); GPU ile gecikme de düşer.
- **Anomali doğrulama (Prompt 2)**: M3'te uygulanmadı, ilerideki milestone'da lokal Ollama ile aktive.
- **Embedding tabanlı snapshot araması**: "kırmızı dorseli tırları göster" gibi.
