# 06 — LLM Stratejisi

## Genel Felsefe

LLM **ucuz değil, sadece doğru yerde kullanılırsa ucuzdur.** Bu projede LLM şu işler için kullanılır:

1. **Tır + dorse renk ayrımı** (Frigate yapamaz)
2. **Anomali doğrulama** (örn. "bu kişi düşmüş mü?")
3. **Yetkisiz alan ihlali doğrulaması** (M8'de, yüz tanıma ekledikten sonra)

Frigate'in yapabildiği işler için **asla** LLM çağrılmaz: kişi tespiti, araç tespiti, basit hareket.

## Model Seçimi

**Claude Haiku 4.5** (`claude-haiku-4-5-20251001`)

| Neden | Detay |
|---|---|
| Ucuz | $0,80/M input, $4/M output |
| Hızlı | ~1–2 saniye yanıt |
| Vizyon destekler | Görüntü tabanlı analiz |
| Yapısal çıktı iyi | JSON döndürme güvenilir |
| Anthropic SDK | Prompt caching desteği var |

Alternatifler değerlendirildi:
- **Gemini 2.5 Flash**: ~3× daha ucuz, ama Anthropic SDK altyapısına bağlanmak istiyoruz, vendor-neutrality şimdilik öncelik değil
- **Sonnet 4.6**: 4× pahalı, gerek yok
- **GPT-4o-mini**: alternatif, port edilebilir mimari isteniyorsa

## Prompt Caching

Her LLM çağrısında sistem prompt'unu cache'leyeceğiz:

```python
messages = [{
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        },
        {"type": "image", "source": {...}},
        {"type": "text", "text": user_question},
    ]
}]
```

Cache hit oranı %80+ olur (sistem prompt sabit), input maliyetini %90 azaltır.

## Prompt 1: Tır + Dorse Renk Analizi

### Sistem Prompt (cached)

```text
Sen bir araç görüntü analiz asistanısın. Sana endüstriyel tesise giren bir kamyonun
görüntüsü verilecek. Aşağıdakileri tespit edip JSON döndüreceksin.

ÖNEMLİ:
- Sadece JSON döndür, başka açıklama yapma.
- Plaka okumaya çalışma, sadece renk ve genel bilgi.
- Emin değilsen guven düşür.
- Renk için temel renk listesi: beyaz, siyah, gri, kirmizi, mavi, yesil, sari,
  turuncu, kahverengi, mor, pembe, lacivert, krem, bordo, metalik

Cevap şeması:
{
  "tir_var_mi": boolean,
  "cekici_rengi": string | null,
  "dorse_var_mi": boolean,
  "dorse_rengi": string | null,
  "dorse_tipi": "tenteli" | "frigo" | "konteyner" | "acik" | "tanker" | "bilinmeyen" | null,
  "yon": "giris" | "cikis" | "duruyor" | null,
  "guven": float (0.0 - 1.0),
  "notlar": string | null
}
```

### Kullanıcı mesajı

```text
[image]
Bu kamyonu analiz et.
```

### Çıktı doğrulama (Pydantic)

```python
class TruckAnalysis(BaseModel):
    tir_var_mi: bool
    cekici_rengi: Optional[Color]
    dorse_var_mi: bool
    dorse_rengi: Optional[Color]
    dorse_tipi: Optional[TrailerType]
    yon: Optional[Direction]
    guven: float = Field(ge=0.0, le=1.0)
    notlar: Optional[str]
```

`guven < 0.5` ise → sonucu DB'ye `low_confidence=true` flag'i ile yaz, alarm üretme ama insan incelemesi için işaretle.

## Prompt 2: Anomali Doğrulama

Frigate "person" tespit etti, hareket pattern'i şüpheli (örn. çok hızlı düşüş, çok uzun süre sabit duruş). Bridge bunu opsiyonel olarak Haiku'ya doğrulatır.

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

## Maliyet Kontrolü

### Per-çağrı maliyet hesabı

| Bileşen | Token | Maliyet ($) |
|---|---|---|
| System prompt (cached) | 400 | 0,80 × 0,1 / 1000 = 0,00003 |
| Görüntü (640×480) | ~400 | 400 × 0,80/1M = 0,00032 |
| User msg | 50 | 0,00004 |
| Output JSON | 200 | 200 × 4/1M = 0,0008 |
| **Toplam per çağrı** | | **~$0,0012** |

### Aylık tahmin (sizin senaryo)

| Olay | Çağrı/ay | Maliyet |
|---|---|---|
| Tır renk (20/gün × 30) | 600 | $0,72 |
| Anomali doğrulama | 300 | $0,36 |
| Yetkisiz alan (M8+) | 150 | $0,18 |
| **Toplam aylık** | **~1.050** | **~$1,26** |

### Bütçe Guard (Sabit)

| Faz | Bütçe | Uyarı | Disable |
|---|---|---|---|
| PoC | $10/ay | $8 | $10 |
| Production | $25/ay | $20 | $25 |

Bridge'de:

```python
LLM_MONTHLY_BUDGET_USD = float(os.environ["LLM_MONTHLY_BUDGET_USD"])  # 10 veya 25

async def check_budget():
    used = await db.sum_llm_cost_this_month()
    if used > LLM_MONTHLY_BUDGET_USD * 0.8:
        await alert(f"LLM bütçesinin %80'i tüketildi: ${used:.2f}/${LLM_MONTHLY_BUDGET_USD}")
    if used > LLM_MONTHLY_BUDGET_USD:
        await alert(f"LLM bütçesi aşıldı (${used:.2f}), çağrılar durduruluyor")
        return False
    return True
```

`llm_usage` tablosu:

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  call_type TEXT,           -- 'truck_color' | 'anomaly' | ...
  model TEXT,
  input_tokens INT,
  output_tokens INT,
  cached_tokens INT,
  cost_usd NUMERIC(10,6),
  latency_ms INT,
  success BOOLEAN,
  error TEXT
);
```

## Hata ve Retry

- Timeout: 30 saniye
- Retry: 2 deneme (Anthropic SDK kendi yapar)
- Network hatası: bridge yerel kuyrukta tutar, max 1 saat retry
- API hatası (4xx): log + ölü mektup, retry yok
- 529 (overloaded): exponential backoff

## Test Set

Pilot fazda her tipte 20 görüntü:
- Tır + dorse (5 farklı renk kombinasyonu)
- Plaka okunamayan zor açı
- Gece görüntüsü (IR mode)
- Yağmurlu/sisli
- Multiple araç aynı karede

Beklenen başarı: %90+ doğru renk ataması.

## İleride

- **Local LLM fallback**: LM Studio + Qwen2.5-VL 7B → toplam offline çalışma (gerektiğinde)
- **Batch API**: Anthropic Batch API ile %50 indirim (gerçek-zamansız olaylar için)
- **Embedding tabanlı snapshot araması**: "kırmızı dorseli tırları göster" gibi
