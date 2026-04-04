from __future__ import annotations

from src.models.crop_profiles import CropProfile, FeatureRequirement
from src.scoring.suitability import score_point


def _fmt_value(name: str, value: float) -> str:
    if name == "mean_temp_c":
        return f"{value:.1f} °C"
    if name == "rainfall_mm":
        return f"{value:.0f} mm (annualized)"
    if name == "frost_risk":
        return f"{100.0 * value:.1f}% of hours at or below freezing"
    if name == "humidity_pct":
        return f"{value:.1f}%"
    if name == "et0_mm":
        return f"{value:.0f} mm reference ET (annualized)"
    if name == "wind_speed_10m_kmh":
        return f"{value:.1f} km/h"
    if name == "soil_moisture_1_3cm":
        return f"{value:.3f} (fraction)"
    if name == "weather_stress_ratio":
        return f"{100.0 * value:.1f}% of hours with severe weather codes"
    if name == "soil_ph":
        return f"{value:.2f}"
    if name == "soil_organic_carbon_gkg":
        return f"{value:.1f} g/kg"
    if name in ("clay_pct", "sand_pct"):
        return f"{value:.1f}%"
    return f"{value:.3g}"


def _label(name: str) -> str:
    return {
        "mean_temp_c": "Mean temperature",
        "rainfall_mm": "Rainfall",
        "frost_risk": "Frost exposure",
        "humidity_pct": "Relative humidity",
        "et0_mm": "Reference evapotranspiration (ET0)",
        "wind_speed_10m_kmh": "Wind speed",
        "soil_moisture_1_3cm": "Surface soil moisture",
        "weather_stress_ratio": "Severe-weather stress",
        "soil_ph": "Soil pH",
        "soil_organic_carbon_gkg": "Soil organic carbon",
        "clay_pct": "Clay content",
        "sand_pct": "Sand content",
    }.get(name, name.replace("_", " "))


def _ideal_span(req: FeatureRequirement) -> str:
    return f"{req.ideal_min:g}–{req.ideal_max:g}"


def _hard_span(req: FeatureRequirement) -> str:
    return f"{req.hard_min:g}–{req.hard_max:g}"


def build_site_reasoning(row: dict[str, Any], profile: CropProfile) -> str:
    """
    Plain-language strengths, trade-offs, and data gaps vs crop profile thresholds.
    """
    details = score_point(row, profile)
    crop = profile.name
    pid = row.get("point_id", "?")
    score = float(row.get("score") or 0.0)
    band = row.get("score_band") or "unknown"

    strengths: list[str] = []
    tradeoffs: list[str] = []
    critical: list[str] = []

    ordered = sorted(
        profile.requirements.items(),
        key=lambda kv: -kv[1].weight,
    )

    for name, req in ordered:
        label = _label(name)
        raw = row.get(name)
        if raw is None or name in details.missing_features:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue

        shown = _fmt_value(name, value)

        if name in details.hard_violations or not (req.hard_min <= value <= req.hard_max):
            critical.append(
                f"{label} is {shown}, outside the viable range ({_hard_span(req)}) for {crop} "
                f"(ideal {_ideal_span(req)}). This heavily penalizes suitability."
            )
        elif req.ideal_min <= value <= req.ideal_max:
            strengths.append(
                f"{label} ({shown}) is within the ideal band ({_ideal_span(req)}) for {crop}."
            )
        elif value < req.ideal_min:
            tradeoffs.append(
                f"{label} is {shown}, below the ideal range ({_ideal_span(req)}) but still inside "
                f"acceptable bounds ({_hard_span(req)}), so growth potential may be reduced."
            )
        else:
            tradeoffs.append(
                f"{label} is {shown}, above the ideal range ({_ideal_span(req)}) but still inside "
                f"acceptable bounds ({_hard_span(req)}), which can add stress or management needs."
            )

    intro = (
        f"Best-ranked site {pid} for {crop} scores {score:.1f}% ({band}), based on matching "
        f"weather and soil signals to crop-specific ideal and limit ranges. "
        f"Confidence reflects how many inputs were present (about {details.confidence:.0%} here)."
    )

    sections: list[str] = [intro]
    if strengths:
        picked = strengths[:7]
        tail = f" (+{len(strengths) - len(picked)} more positives)" if len(strengths) > len(picked) else ""
        sections.append("What looks strong: " + " ".join(picked) + tail)
    if tradeoffs:
        picked = tradeoffs[:5]
        tail = f" (+{len(tradeoffs) - len(picked)} more)" if len(tradeoffs) > len(picked) else ""
        sections.append("What is acceptable but not ideal: " + " ".join(picked) + tail)
    if critical:
        sections.append("What works against the site: " + " ".join(critical[:5]))
    if details.missing_features:
        miss = ", ".join(_label(n) for n in details.missing_features[:12])
        more = " (and more)" if len(details.missing_features) > 12 else ""
        sections.append(
            f"Data limitations: no values for {miss}{more}. "
            "Those gaps reduce confidence and apply a scoring penalty."
        )

    if len(sections) == 1:
        sections.append(
            "Too few measured features overlapped the crop profile to describe strengths or limits."
        )

    return "\n\n".join(sections)
