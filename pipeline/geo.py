"""Country detection from free-text locations. Deterministic: names, aliases, a short list of
academic cities, US state codes, and the '(CN)' suffix style used by Nature Careers."""
import re

COUNTRIES = {
    "AF": ["afghanistan"], "AL": ["albania"], "DZ": ["algeria"], "AR": ["argentina"], "AM": ["armenia", "yerevan"],
    "AU": ["australia", "sydney", "melbourne", "brisbane", "canberra", "perth", "adelaide"],
    "AT": ["austria", "vienna", "graz", "innsbruck"], "AZ": ["azerbaijan", "baku"], "BD": ["bangladesh", "dhaka"],
    "BY": ["belarus", "minsk"], "BE": ["belgium", "brussels", "leuven", "ghent", "louvain"], "BR": ["brazil", "sao paulo", "são paulo", "rio de janeiro"],
    "BG": ["bulgaria", "sofia"], "CA": ["canada", "toronto", "vancouver", "montreal", "montréal", "ottawa", "waterloo", "calgary", "alberta", "british columbia", "ontario", "quebec", "québec"],
    "CL": ["chile", "santiago"], "CN": ["china", "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "wuhan", "nanjing", "suzhou", "ningbo", "zhuhai", "xiamen", "jinan", "qingdao", "lanzhou", "harbin", "changsha", "dalian", "chongqing", "kunming", "macau", "macao", "dongguan", "foshan", "shantou", "zhejiang", "jiangsu", "guangdong", "sichuan", "shandong", "hong kong", "chengdu", "xi'an", "tianjin", "hefei"],
    "CO": ["colombia", "bogota", "bogotá"], "HR": ["croatia", "zagreb"], "CY": ["cyprus"], "CZ": ["czech republic", "czechia", "prague"],
    "DK": ["denmark", "copenhagen", "aarhus", "odense"], "EG": ["egypt", "cairo"], "EE": ["estonia", "tallinn", "tartu"],
    "ET": ["ethiopia", "addis ababa"], "FI": ["finland", "helsinki", "espoo", "tampere", "oulu", "turku"],
    "FR": ["france", "paris", "lyon", "toulouse", "grenoble", "marseille", "strasbourg", "montpellier", "saclay", "orsay", "lille"],
    "GE": ["georgia (country)", "tbilisi"], "DE": ["germany", "berlin", "munich", "münchen", "hamburg", "heidelberg", "göttingen", "goettingen", "dresden", "aachen", "karlsruhe", "stuttgart", "freiburg", "bonn", "cologne", "köln", "leipzig", "jena", "tübingen", "frankfurt", "mainz", "darmstadt", "potsdam", "bremen", "hannover", "saarbrücken", "konstanz", "mannheim", "düsseldorf", "kiel", "münster", "würzburg", "regensburg", "erlangen", "garching", "jülich"],
    "GH": ["ghana", "accra"], "GR": ["greece", "athens", "thessaloniki", "crete"], "HU": ["hungary", "budapest"],
    "IS": ["iceland", "reykjavik"], "IN": ["india", "new delhi", "delhi", "mumbai", "bangalore", "bengaluru", "chennai", "hyderabad", "kolkata", "pune", "kanpur", "kharagpur", "roorkee"],
    "ID": ["indonesia", "jakarta"], "IR": ["iran", "tehran"], "IQ": ["iraq", "baghdad"], "IE": ["ireland", "dublin", "galway", "cork"],
    "IL": ["israel", "tel aviv", "jerusalem", "haifa", "rehovot", "technion", "weizmann"],
    "IT": ["italy", "rome", "milan", "bologna", "padova", "padua", "turin", "torino", "florence", "pisa", "naples", "trieste", "trento", "genoa", "pavia"],
    "JP": ["japan", "tokyo", "kyoto", "osaka", "nagoya", "tsukuba", "okinawa", "sendai", "riken", "hokkaido"],
    "JO": ["jordan (country)", "amman"], "KZ": ["kazakhstan", "astana", "almaty", "nur-sultan", "nur sultan"], "KE": ["kenya", "nairobi"],
    "KR": ["south korea", "korea", "seoul", "daejeon", "kaist", "pohang", "busan"], "KW": ["kuwait"], "KG": ["kyrgyzstan", "bishkek"],
    "LV": ["latvia", "riga"], "LB": ["lebanon", "beirut"], "LT": ["lithuania", "vilnius"], "LU": ["luxembourg"],
    "MY": ["malaysia", "kuala lumpur"], "MX": ["mexico", "mexico city"], "MD": ["moldova"], "MN": ["mongolia", "ulaanbaatar"],
    "MA": ["morocco", "rabat"], "NP": ["nepal", "kathmandu"], "NL": ["netherlands", "the netherlands", "amsterdam", "delft", "leiden", "utrecht", "eindhoven", "groningen", "wageningen", "rotterdam", "nijmegen", "twente", "maastricht"],
    "NZ": ["new zealand", "auckland", "wellington", "otago"], "NG": ["nigeria", "lagos", "abuja"], "NO": ["norway", "oslo", "bergen", "trondheim", "tromsø", "tromso", "ntnu"],
    "OM": ["oman"], "PK": ["pakistan", "islamabad", "lahore", "karachi"], "PE": ["peru", "lima"], "PH": ["philippines", "manila"],
    "PL": ["poland", "warsaw", "krakow", "kraków", "wroclaw", "wrocław", "gdansk", "poznan", "poznań"], "PT": ["portugal", "lisbon", "porto", "coimbra", "braga"],
    "QA": ["qatar", "doha"], "RO": ["romania", "bucharest", "cluj"], "RU": ["russia", "moscow", "st. petersburg", "saint petersburg", "novosibirsk", "skoltech"],
    "SA": ["saudi arabia", "riyadh", "kaust", "thuwal", "jeddah"], "RS": ["serbia", "belgrade"], "SG": ["singapore"], "SK": ["slovakia", "bratislava"],
    "SI": ["slovenia", "ljubljana"], "ZA": ["south africa", "cape town", "johannesburg", "pretoria", "stellenbosch"],
    "ES": ["spain", "madrid", "barcelona", "valencia", "seville", "sevilla", "granada", "bilbao", "zaragoza", "san sebastian"],
    "LK": ["sri lanka", "colombo"], "SE": ["sweden", "stockholm", "uppsala", "lund", "gothenburg", "göteborg", "linköping", "umeå", "kth"],
    "CH": ["switzerland", "zurich", "zürich", "geneva", "genève", "lausanne", "basel", "bern", "epfl", "eth zurich", "villigen", "fribourg", "neuchâtel"],
    "TW": ["taiwan", "taipei", "hsinchu"], "TJ": ["tajikistan", "dushanbe"], "TZ": ["tanzania"], "TH": ["thailand", "bangkok"],
    "TM": ["turkmenistan", "ashgabat"], "TN": ["tunisia", "tunis"], "TR": ["turkey", "türkiye", "turkiye", "ankara", "istanbul", "izmir"],
    "UG": ["uganda", "kampala"], "UA": ["ukraine", "kyiv", "kiev", "kharkiv", "lviv"], "AE": ["united arab emirates", "uae", "abu dhabi", "dubai", "masdar", "mbzuai", "sharjah"],
    "GB": ["united kingdom", "u.k.", "england", "scotland", "wales", "northern ireland", "great britain", "london", "oxford", "cambridge", "edinburgh", "manchester", "glasgow", "bristol", "birmingham", "leeds", "sheffield", "nottingham", "southampton", "liverpool", "durham", "warwick", "exeter", "bath", "newcastle", "cardiff", "belfast", "aberdeen", "st andrews", "york", "lancaster", "leicester", "reading", "sussex", "surrey", "loughborough", "norwich", "swansea", "coventry", "brighton", "harwell", "dundee", "strathclyde", "heriot-watt", "kent", "essex", "plymouth", "keele", "bangor", "canterbury", "hull", "oxfordshire", "cheshire"],
    "US": ["united states", "usa", "u.s.", "america", "boston", "new york", "california", "los angeles", "san francisco", "stanford", "berkeley", "pasadena", "seattle", "chicago", "pittsburgh", "philadelphia", "houston", "austin", "atlanta", "washington dc", "washington, dc", "baltimore", "ann arbor", "princeton", "cambridge, ma", "madison", "minneapolis", "san diego", "boulder", "denver", "salt lake city", "raleigh", "durham, nc", "ithaca", "new haven", "providence", "pennsylvania", "massachusetts", "texas", "florida", "michigan", "ohio", "virginia", "new jersey", "illinois", "indiana", "arizona", "colorado", "oregon", "georgia, usa", "tennessee", "maryland", "wisconsin", "iowa", "kansas", "nebraska", "missouri", "oklahoma", "kentucky", "alabama", "louisiana", "carolina", "connecticut", "utah", "nevada", "hawaii", "alaska", "idaho", "montana", "wyoming", "dakota", "mississippi", "arkansas", "vermont", "new hampshire", "maine", "delaware", "new mexico"],
    "UZ": ["uzbekistan", "tashkent", "samarkand"], "VE": ["venezuela"], "VN": ["vietnam", "hanoi", "ho chi minh"],
}
# Names that are also ordinary words or other places need context; they are listed with a qualifier above
# ("georgia (country)") and matched only through their cities or the explicit country code.
_AMBIGUOUS_NAMES = {"georgia (country)": "georgia"}

US_STATE_CODES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
                  "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()

_name_to_code = {}
for code, names in COUNTRIES.items():
    for n in names:
        _name_to_code[n.lower()] = code
_ALT = "|".join(re.escape(n) for n in sorted(_name_to_code, key=len, reverse=True))
_NAME_RE = re.compile(r"(?<![\w])(" + _ALT + r")(?![\w])", re.I)
_PAREN_CODE = re.compile(r"\(([A-Z]{2})\)")
_STATE_RE = re.compile(r",\s*(" + "|".join(US_STATE_CODES) + r")\b")
_REMOTE = re.compile(r"\b(remote|work from home|anywhere|hybrid)\b", re.I)


def find_countries(text, default=None):
    """Return a sorted list of ISO codes found in `text`; [default] if none and a default is given."""
    if not text:
        return [default] if default else []
    found = set()
    for m in _PAREN_CODE.finditer(text):
        if m[1] in COUNTRIES:
            found.add(m[1])
    for m in _NAME_RE.finditer(text):
        found.add(_name_to_code[m[1].lower()])
    if _STATE_RE.search(text):
        found.add("US")
    # "Georgia" alone is the country only when no US state context is present; handled via the explicit
    # "(GE)" suffix or Tbilisi. We never guess it from the bare word.
    if not found and default:
        found.add(default)
    return sorted(found)


def is_remote(text):
    return bool(text and _REMOTE.search(text))
