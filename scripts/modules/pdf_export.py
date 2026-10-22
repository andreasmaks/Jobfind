"""Private, on-demand bookmark export; no remote assets or persistent PDF files."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import threading
import time
from zoneinfo import ZoneInfo

from availability import BLOCKED, CLOSED, fetch
from config import CONFIG

EXPORT_LOCK = threading.Lock()


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "form", "aside"}:
            self.skip += 1
        if not self.skip and tag in {"p", "div", "section", "h1", "h2", "h3", "h4", "ul", "ol", "br", "li"}:
            prefix = "- " if tag == "li" else "## " if tag in {"h1", "h2", "h3", "h4"} else ""
            self.parts.append("\n" + prefix)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "form", "aside"}:
            self.skip = max(0, self.skip - 1)
        if not self.skip and tag in {"p", "div", "section", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


def plain(value: str) -> str:
    parser = Text()
    parser.feed(value)
    lines = [re.sub(r"[\t\r ]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def matching_title(expected: str, actual: str) -> bool:
    words = set(re.findall(r"\w{3,}", expected.casefold())) - {"senior", "junior", "divers"}
    found = set(re.findall(r"\w{3,}", actual.casefold()))
    return bool(words) and len(words & found) / len(words) >= .6


def extract_original(job: dict, response: dict) -> tuple[str, str]:
    if response.get("error") or response.get("http") != 200:
        return "", "unavailable"
    raw = response.get("body", "")
    page = plain(raw)
    if BLOCKED.search(page[:2000]) or CLOSED.search(page[:2000]):
        return "", "unavailable"
    postings = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                postings.append(value)
            for key in ("@graph", "mainEntity"):
                if key in value:
                    visit(value[key])
    for script in re.findall(r'<script\b[^>]*type\s*=\s*[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script\s*>', raw, re.I | re.S):
        try:
            visit(json.loads(script))
        except (ValueError, RecursionError):
            continue
    matches = [item for item in postings if matching_title(job.get("title", ""), str(item.get("title", "")))]
    if len(matches) == 1:
        item = matches[0]
        description = item.get("description", "")
        if isinstance(description, str) and len(plain(description)) >= 150:
            fragments = [description]
            for key in ("responsibilities", "qualifications", "skills", "jobBenefits"):
                value = item.get(key)
                if isinstance(value, str) and value and plain(value) not in plain(description):
                    fragments.append(value)
            return plain("\n".join(fragments)), "structured"
    # Do not mistake a portal search page or a different job for the original ad.
    if postings:
        return "", "unavailable"
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1\s*>", raw, re.I | re.S)
    if not heading or not matching_title(job.get("title", ""), plain(heading[1])):
        return "", "unavailable"
    main = re.search(r"<(main|article)\b[^>]*>(.*?)</\1\s*>", raw, re.I | re.S)
    content = plain(main[2]) if main else page
    return (content, "page") if len(content) >= 300 else ("", "unavailable")


def originals(jobs: list[dict], fetcher=fetch, budget: float = 45) -> list[tuple[str, str]]:
    results = [("", "unavailable") for _ in jobs]
    deadline = time.monotonic() + budget
    def read(job):
        if time.monotonic() >= deadline:
            return "", "unavailable"
        try:
            return extract_original(job, fetcher(job["original_url"]))
        except Exception:
            return "", "unavailable"
    pool = ThreadPoolExecutor(max_workers=4)
    futures = {pool.submit(read, job): index for index, job in enumerate(jobs[:100])}
    try:
        done, _ = wait(futures, timeout=budget)
        for future in done:
            results[futures[future]] = future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def build_pdf(jobs: list[dict], language: str = "de", fetcher=fetch) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak, Table, TableStyle

    if not jobs:
        raise ValueError("no_saved_jobs")
    english = language == "en"
    def tr(de, en):
        return en if english else de
    # ReportLab ships these fonts; no private font assets are bundled or fetched.
    import reportlab
    font_dir = Path(reportlab.__file__).parent / "fonts"
    # Font setup is also safe for repeated exports in the same server process.
    if "Jobfind" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Jobfind", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("Jobfind-Bold", str(font_dir / "VeraBd.ttf")))
    ink = colors.HexColor("#16243b")
    muted = colors.HexColor("#647285")
    accent = colors.HexColor("#00b99c")
    styles = {
        "title": ParagraphStyle("title", fontName="Jobfind-Bold", fontSize=23, leading=29, textColor=ink, spaceAfter=12),
        "company": ParagraphStyle("company", fontName="Jobfind-Bold", fontSize=12, leading=18, textColor=accent, spaceAfter=8),
        "h": ParagraphStyle("h", fontName="Jobfind-Bold", fontSize=12, leading=18, textColor=ink, spaceBefore=18, spaceAfter=8, keepWithNext=True),
        "body": ParagraphStyle("body", fontName="Jobfind", fontSize=10, leading=15, textColor=ink, spaceAfter=7, splitLongWords=True),
        "small": ParagraphStyle("small", fontName="Jobfind", fontSize=8, leading=12, textColor=muted, spaceAfter=6),
    }
    def p(text, style="body"):
        # External HTML is never interpreted as PDF markup, links or images.
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), styles[style])
    now = datetime.now(ZoneInfo(CONFIG["timezone"]))
    timestamp = now.strftime("%d.%m.%Y %H:%M")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=60, bottomMargin=52,
                            title=tr("Jobfind - Gemerkte Stellen", "Jobfind - Saved jobs"), author="Jobfind")
    story = [p("jobfind", "company"), p(tr("Deine gemerkten Stellen", "Your saved jobs"), "title"),
             p(tr(f"{len(jobs)} Anzeigen | Export vom {timestamp}", f"{len(jobs)} listings | Exported {timestamp}"), "small"),
             p(tr("Alle Lesezeichen in einer Datei. Zuerst die Übersicht und vorhandene Einschätzung, danach der einheitlich aufbereitete Text der Originalanzeige. Die Texte bleiben in ihrer Originalsprache.",
                  "All saved jobs in one file. Each listing starts with a summary and existing assessment, followed by consistently formatted original text. Listing text retains its original language.")),
             p(tr("Die Einschätzungen stammen aus Jobfind und sind keine neue Bewertung. Verfügbarkeit und Angaben können sich nach dem Export ändern.",
                  "Assessments come from Jobfind and are not a new evaluation. Availability and details may change after export."), "small"),
             p(tr("Inhalt", "Contents"), "h")]
    for index, job in enumerate(jobs, 1):
        story.append(p(f"{index:02d}  {job['title']} - {job['company']}"))
    texts = originals(jobs, fetcher)
    for index, (job, (original, method)) in enumerate(zip(jobs, texts), 1):
        story.extend([PageBreak(), p(f"{index:02d} / {len(jobs):02d}    {job['company']}", "company"), p(job["title"], "title")])
        facts = [job.get("location"), job.get("hours"), job.get("remote"), job.get("employment_type")]
        if job.get("score") is not None:
            facts.append(tr(f"Passung {job['score']}/10", f"Match {job['score']}/10"))
        box = Table([[p("\n".join(str(value) for value in facts if value))]], colWidths=[doc.width])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e5f8f3")), ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(box)
        for key, label in (("summary", tr("Auf einen Blick", "At a glance")), ("fit", tr("Warum es passen könnte", "Why it could fit")), ("concerns", tr("Darauf solltest du achten", "Things to consider"))):
            if job.get(key):
                story.extend([p(label, "h"), p(job[key])])
        story.append(p(tr("Originalanzeige", "Original listing"), "h"))
        url = str(job["original_url"])
        if url.startswith(("https://", "http://")):
            story.append(Paragraph(f'<link href="{escape(url, quote=True)}" color="#008574">{escape(url)}</link>', styles["small"]))
        else:
            story.append(p(url, "small"))
        if original:
            notice = tr("Text der Originalseite, automatisch ausgelesen und einheitlich formatiert. Bilder und das Layout der Quellseite werden nicht übernommen; die Vollständigkeit ist nicht garantiert.",
                        "Text extracted from the original page and consistently formatted. Source images and layout are not included; completeness is not guaranteed.")
            story.append(p(notice, "small"))
            for line in original.splitlines():
                story.append(p(line[3:] if line.startswith("## ") else line, "h" if line.startswith("## ") else "body"))
        else:
            story.append(p(tr("Der Originaltext konnte nicht zuverlässig abgerufen werden (z. B. Zugriffsschutz, abgelaufene Anzeige oder technische Einschränkung). Die obige Zusammenfassung ist der gespeicherte Jobfind-Stand, nicht die vollständige Originalanzeige.",
                              "The original text could not be reliably retrieved (e.g. access protection, an expired listing or technical restrictions). The summary above is the saved Jobfind snapshot, not the complete original listing.")))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Jobfind", 8)
        canvas.setFillColor(muted)
        canvas.drawString(48, 28, "jobfind  |  " + timestamp)
        canvas.drawRightString(A4[0] - 48, 28, tr("Seite ", "Page ") + str(document.page))
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(2)
        canvas.line(48, A4[1] - 34, A4[0] - 48, A4[1] - 34)
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
