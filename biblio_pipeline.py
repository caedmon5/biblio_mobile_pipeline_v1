import requests, json, os, re, time, bibtexparser
from config import ZOTERO_API_KEY, ZOTERO_USER_ID, ZOTERO_USERNAME
from bibtexparser.bparser import BibTexParser

def load_bibtex_entries(bibtex_str):
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    parser.interpolate_strings = True
    db = bibtexparser.loads(bibtex_str, parser=parser)
    return db.entries  # list of dicts

def extract_year(entry):
    date_str = entry.get("date", "")
    match = re.search(r'\b(\d{4})\b', date_str)
    if match:
        return match.group(1)
    year_str = entry.get("year", "")
    match = re.search(r'\b(\d{4})\b', year_str)
    if match:
        return match.group(1)
    return "XXXX"

def generate_citekey(entry):
    author = entry.get("author", "Unknown")
    title = entry.get("title", "")
    year = extract_year(entry)

    # Extract last name from author field
    first_author = author.split(" and ")[0]
    if "," in first_author:
        lastname = re.sub(r'[^A-Za-z]', '', first_author.split(",")[0])
    else:
        lastname = re.sub(r'[^A-Za-z]', '', first_author.split()[-1])

    # First three words of title
    title_words = re.findall(r'\b\w+\b', title)
    slug = ''.join(word.capitalize() for word in title_words[:3])

    return f"{lastname}{year}{slug}"

def generate_filename(entry):
    author = entry.get("author", "Unknown")
    title = entry.get("title", "")
    year = extract_year(entry)


    # Split author into capitalized parts
    name_parts = [w.capitalize() for w in author.replace('-', ' ').split()]
    lastname_parts = name_parts[-2:] if len(name_parts) >= 2 else name_parts[-1:]

    # Title-cased first 3 words
    title_words = re.findall(r'\b\w+\b', title)
    title_part = ' '.join(w.capitalize() for w in title_words[:3])

    return f"LN {' '.join(lastname_parts)} {year} {title_part}.md"


# Dynamic base path
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
import platform

if "ANDROID_STORAGE" in os.environ or platform.system() == "Linux" and "com.termux" in os.environ.get("HOME", ""):
    # Android (e.g. Termux or Pydroid)
    OBSIDIAN_PATH = "/sdcard/Documents/Obsidian/LN Literature Notes"
else:
    # Default to Linux desktop
    OBSIDIAN_PATH = "/home/dan/wealtheow/LN Literature Notes"

LOG_PATH = os.path.join(BASE_PATH, "output", "biblio-log")

# Ensure output directories exist
os.makedirs(OBSIDIAN_PATH, exist_ok=True)
os.makedirs(LOG_PATH, exist_ok=True)

def extract_blocks(text, start_marker, end_marker):
    pattern = rf"{start_marker}(.*?){end_marker}"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None

def parse_bibtex(bibtex):
    entry = {}
    lines = bibtex.splitlines()
    for line in lines:
        if '=' in line:
            k, v = line.split('=', 1)
            entry[k.strip()] = v.strip().strip('{}",')
    entry["ID"] = re.search(r'@\w+\{([^,]+),', bibtex).group(1)
    return entry

def zotero_upload(entry):
    headers = {'Zotero-API-Key': ZOTERO_API_KEY, 'Content-Type': 'application/json'}
    metadata = [{
        "itemType": "journalArticle",
        "title": entry.get("title", ""),
        "creators": [{"creatorType": "author", "name": entry.get("author", "Unknown")}],
        "publicationTitle": entry.get("journal", ""),
        "date": entry.get("date", ""),
        "url": entry.get("url", ""),
        "abstractNote": entry.get("abstract", ""),
        "extra": entry.get("note", ""),
        "tags": [{"tag": k.strip()} for k in entry.get("keywords", "").split(',')]
}]

    r = requests.post(
        f"https://api.zotero.org/users/{ZOTERO_USER_ID}/items",
        headers=headers,
        data=json.dumps(metadata)
    )

    try:
        return r.status_code, r.json()
    except requests.exceptions.JSONDecodeError:
        return r.status_code, {"error": "No JSON returned", "body": r.text}

def build_markdown(entry, citekey=None, zotero_key=None):
    zotero_url = f"https://www.zotero.org/{ZOTERO_USERNAME}/items/{zotero_key}" if zotero_key else ""
    md = f"""---
citekey: "{citekey or entry.get('ID', 'UNKNOWN')}"
type: "article"
zotero_key: "{zotero_key or ''}"
zotero_url: "{zotero_url}"
zotero_library_id: {ZOTERO_USER_ID}
autoupdate: true
---
# Chicago Author-Year  Bibliography
{entry.get('author', '')}. {entry.get('date', '')}. "{entry.get('title', '')}." *{entry.get('journal', '')}*. {entry.get('url', '')}

# Abstract  
{entry.get('abstract', 'TBD')}

# Keywords
{', '.join(f"[[{k.strip()}]]" for k in entry.get("keywords", "").split(','))}

# Notes  
{entry.get('note', 'TBD')}

# Related Files and URLs.  
{zotero_url}
"""
    return md

def save_file(content, filename, path):
    full_path = os.path.join(path, filename)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

def log_run(data, citekey):
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_filename = f"biblio_log_{citekey}_{ts}.json"
    save_file(json.dumps(data, indent=2), log_filename, LOG_PATH)

def main(text, commit=False):
    if "@bibtex" in text and "@end" in text:
        bibtex_raw = extract_blocks(text, "@bibtex", "@end")
    else:
        print("🔎 No @bibtex block markers found — assuming entire input is raw BibTeX.")
        bibtex_raw = text.strip()

    if not bibtex_raw.startswith("@"):
        print("❌ Input does not appear to be valid BibTeX.")
        return

    # Optional: warn if markdown block is still present (legacy input)
    if "@markdown" in text:
        print("⚠️ Detected @markdown block — ignored. Markdown is now built from Zotero.")

    # Find all BibTeX blocks in the input (supporting multiple)
    entries = load_bibtex_entries(bibtex_raw)

    if not entries:
        print("❌ No BibTeX entries found.")
        return

    for bib in entries:
        citekey = generate_citekey(bib)
        print(f"\n✅ Parsed citekey: {citekey}")
        if not commit:
            print("🟡 Dry-run mode. No Zotero upload or file write.")
            print(json.dumps(bib, indent=2))
            filename = generate_filename(bib)
            print(f"\n📄 Would write file: {filename}")
            print("📦 Markdown preview:\n")
            md = build_markdown(bib, citekey=citekey)
            print(md)

        else:
            status, resp = zotero_upload(bib)
            if status in [200, 201]:
                zotero_item = resp['successful']['0']
                key = zotero_item['key']
                print(f"✅ Zotero upload successful (Key: {key})")
                md = build_markdown(bib, citekey=citekey, zotero_key=key)
                year = extract_year(bib)

                citekey = generate_citekey(bib)

                filename = generate_filename(bib)
                save_file(md, filename, OBSIDIAN_PATH)
                print(f"✅ Markdown saved: {filename}")
                log_run({"bibtex": bib, "zotero_response": zotero_item}, citekey)
            else:
                print(f"❌ Zotero upload failed: {status}")
                print(json.dumps(resp, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Actually upload to Zotero and write files")
    args = parser.parse_args()

    import platform

    if platform.system() == "Linux" and not os.environ.get("PREFIX"):
        import pyperclip
        input_text = pyperclip.paste()
        print("📋 Clipboard input (Linux) detected and loaded.")
        with open("input.txt", "w", encoding="utf-8") as f:
            f.write(input_text)
    elif os.environ.get("PREFIX"):  # Android Termux
        import subprocess
        try:
            clipboard = subprocess.check_output(["termux-clipboard-get"]).decode("utf-8")
            print("📋 Android clipboard detected via termux-clipboard-get.")
            with open("input.txt", "w", encoding="utf-8") as f:
                f.write(clipboard)
            print("📋 Clipboard input (Android/Termux) saved to input.txt.")
            input_text = clipboard
        except Exception as e:
            print(f"❌ Failed to read clipboard: {e}")
            exit(1)
    else:
        with open("input.txt", encoding="utf-8") as f:
            input_text = f.read()
        print("📄 Loaded input from file.")

    print(f"🚦 Running in {'COMMIT' if args.commit else 'DRY-RUN'} mode.")
    main(input_text, commit=args.commit)


