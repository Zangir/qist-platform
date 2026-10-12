from datetime import date

from pipeline import geo, taxonomy
from pipeline.common import clean, parse_date, item_id


def test_clean_strips_markup_and_entities():
    assert clean("<p>A &amp; B <b>bold</b></p>\n  next") == "A & B bold next"
    assert clean("word " * 200, limit=50).endswith("…") and len(clean("word " * 200, limit=50)) <= 51


def test_parse_date_formats():
    ref = date(2026, 10, 12)
    assert parse_date("2026-11-04T00:00:00", ref) == date(2026, 11, 4)
    assert parse_date("Mon, 12 Oct 2026 08:00:57 +0000") == date(2026, 10, 12)
    assert parse_date("October 14, 2026") == date(2026, 10, 14)
    assert parse_date("09 Nov", ref) == date(2026, 11, 9)
    assert parse_date("15 November", ref) == date(2026, 11, 15)
    assert parse_date("12 Jan", ref) == date(2027, 1, 12)        # rolls forward past year end
    assert parse_date("30 Dec", ref) == date(2025, 12, 30) or parse_date("30 Dec", ref) == date(2026, 12, 30)
    assert parse_date("10/01/2026") == date(2026, 10, 1)         # Grants.gov MM/DD/YYYY
    assert parse_date("garbage") is None and parse_date("") is None


def test_item_id_is_stable_and_kind_prefixed():
    assert item_id("job", "u") == item_id("job", "u") and item_id("job", "u")[0] == "j" and item_id("grant", "u") != item_id("job", "u")


def test_fields_basic():
    assert taxonomy.classify_fields("Neural network decoders for quantum error correction")[:1] == ["Artificial Intelligence"] \
        or "Physics and Physical Sciences" in taxonomy.classify_fields("Neural network decoders for quantum error correction")
    assert "Neuroscience" in taxonomy.classify_fields("Hippocampal place cells encode goals")
    assert "Economics" in taxonomy.classify_fields("Monetary policy and inflation expectations")
    assert taxonomy.classify_fields("Weekly meeting notes") == []


def test_word_boundaries_do_not_misfire():
    # 'ai' must not match inside 'said' / 'maintain'; 'ion' style short tokens likewise
    assert "Artificial Intelligence" not in taxonomy.classify_fields("He said we maintain the trail", "said maintain")
    assert "Artificial Intelligence" in taxonomy.classify_fields("AI for protein design")


def test_hyphen_normalisation_matches_both_spellings():
    assert "Computer Science" in taxonomy.classify_fields("Human-computer interaction in classrooms")
    assert "Computer Science" in taxonomy.classify_fields("Human computer interaction in classrooms")


def test_prior_beats_thin_text():
    assert taxonomy.classify_fields("A short note", "", prior={"Neuroscience": 4}) == ["Neuroscience"]


def test_field_names_match_the_site_list():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "assets/js/app.js").read_text(encoding="utf8")
    site = re.findall(r"'([^']+)'", re.search(r"PRIMARY_FIELDS: \[(.*?)\]", src, re.S)[1])
    assert set(taxonomy.FIELDS) == set(site) - {"Other Research Area"}


def test_stage_detection_titles():
    d = taxonomy.detect_stages
    assert d("PhD Studentship in Chemistry") == ["phd"]
    assert d("Doctoral Researcher (m/f/d) in Astrophysics") == ["phd"]
    assert d("Postdoctoral Research Associate in Astrophysics") == ["postdoc"]
    assert d("Research Fellow in Machine Learning") == ["postdoc"]
    assert d("Assistant Professor of History") == ["faculty"]
    assert d("Lecturer in Economics") == ["faculty"]
    assert d("Postdoctoral Fellow or Assistant Professor") == ["faculty", "postdoc"]
    assert d("Research Scientist, Climate") == ["researcher"]
    assert d("Dining Hall Cook") == []


def test_research_role_filter():
    r = taxonomy.is_research_role
    assert r("PhD Studentship in Chemistry") and r("Professor of Physics") and r("Research Associate in Genomics")
    assert not r("Dining Hall Cook") and not r("Financial Aid Officer") and not r("Software Engineer")
    assert not r("Librarian") and not r("Nurse Practitioner")
    assert r("Software Engineer", "research software for the physics laboratory")


def test_grant_stages_default_and_cues():
    g = taxonomy.grant_stages
    assert g("Graduate Research Fellowship Program") == ["phd"]
    assert "postdoc" in g("Early career researcher award")
    assert g("ERC Advanced Grant 2027") == ["faculty"]
    assert g("Open call for the Digital Society") == ["any"]


def test_countries():
    f = geo.find_countries
    assert f("Beijing (CN)") == ["CN"]
    assert f("Pittsburgh, PA") == ["US"]
    assert f("Cambridge, UK") == ["GB"]
    assert f("Cambridge, MA") == ["US"]
    assert f("Zürich") == ["CH"] and f("Almaty, Kazakhstan") == ["KZ"]
    assert f("Suzhou") == ["CN"]
    assert f("somewhere unknown") == [] and f("", default="GB") == ["GB"]
    assert f("Georgia") == []                      # never guessed from the bare word
    assert geo.is_remote("Remote / Hybrid") and not geo.is_remote("Oxford")
