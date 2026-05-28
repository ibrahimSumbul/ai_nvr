"""LLM Pydantic schema + OllamaClient için testler."""

from __future__ import annotations

import pytest

from bridge.llm import TruckAnalysis


def test_truck_analysis_minimal() -> None:
    """Minimal valid JSON parse."""
    data = {
        "tir_var_mi": True,
        "dorse_var_mi": False,
        "guven": 0.9,
    }
    a = TruckAnalysis.model_validate(data)
    assert a.tir_var_mi is True
    assert a.cekici_rengi is None
    assert a.dorse_var_mi is False
    assert a.guven == 0.9


def test_truck_analysis_full() -> None:
    """Tüm alanlar dolu."""
    data = {
        "tir_var_mi": True,
        "cekici_rengi": "mavi",
        "dorse_var_mi": True,
        "dorse_rengi": "beyaz",
        "dorse_tipi": "tenteli",
        "yon": "giris",
        "guven": 0.85,
        "notlar": "iyi ışık",
    }
    a = TruckAnalysis.model_validate(data)
    assert a.cekici_rengi == "mavi"
    assert a.dorse_rengi == "beyaz"
    assert a.dorse_tipi == "tenteli"
    assert a.yon == "giris"


def test_truck_analysis_invalid_color() -> None:
    """Listede olmayan renk → ValidationError."""
    data = {
        "tir_var_mi": True,
        "cekici_rengi": "şeker pembesi",  # listede yok
        "dorse_var_mi": False,
        "guven": 0.5,
    }
    with pytest.raises(ValueError):
        TruckAnalysis.model_validate(data)


def test_truck_analysis_invalid_trailer_type() -> None:
    """Listede olmayan dorse tipi → ValidationError."""
    data = {
        "tir_var_mi": True,
        "dorse_var_mi": True,
        "dorse_tipi": "vagon",  # listede yok
        "guven": 0.5,
    }
    with pytest.raises(ValueError):
        TruckAnalysis.model_validate(data)


def test_truck_analysis_invalid_guven_range() -> None:
    """guven > 1.0 → ValidationError."""
    data = {
        "tir_var_mi": True,
        "dorse_var_mi": False,
        "guven": 1.5,
    }
    with pytest.raises(ValueError):
        TruckAnalysis.model_validate(data)


def test_truck_analysis_extra_fields_ignored() -> None:
    """Bilinmeyen alan (LLM 'hayal eder') → ignore."""
    data = {
        "tir_var_mi": True,
        "dorse_var_mi": False,
        "guven": 0.8,
        "extra_invented_field": "lala",  # LLM dahil etmiş
    }
    a = TruckAnalysis.model_validate(data)
    assert a.guven == 0.8


def test_truck_analysis_json_string_parse() -> None:
    """Direkt JSON string parse (LLM çıktısı)."""
    raw = '{"tir_var_mi": true, "dorse_var_mi": false, "guven": 0.7}'
    a = TruckAnalysis.model_validate_json(raw)
    assert a.tir_var_mi is True
    assert a.guven == 0.7
