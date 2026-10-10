"""Cache konwersji w Cloud Storage — bez sieci, na atrapie zasobnika.

Sprawdza: (1) bez zmiennej LEGAL_CITE_GCS_BUCKET zasobnik nie jest używany;
(2) pierwsza konwersja zapisuje Markdown i warstwę tekstową do zasobnika;
(3) nowa instancja (pusty katalog lokalny) pobiera je zamiast konwertować;
(4) błąd zasobnika nie przerywa pracy — wraca konwersja.

    python testy/gcs_cache.py
"""
import pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from legal_cite import pdf_tj


class Blob:
    def __init__(self, store, name, awaria):
        self.store, self.name, self.awaria = store, name, awaria
    def exists(self):
        if self.awaria: raise OSError("atrapa: awaria")
        return self.name in self.store
    def download_to_filename(self, f):
        pathlib.Path(f).write_bytes(self.store[self.name])
    def upload_from_filename(self, f):
        if self.awaria: raise OSError("atrapa: awaria")
        self.store[self.name] = pathlib.Path(f).read_bytes()


class Bucket:
    def __init__(self): self.store, self.awaria = {}, False
    def blob(self, name): return Blob(self.store, name, self.awaria)


konwersje = []
def atrapa_konwersji(pdf_path, md_path):
    """Podmienia eli2md: liczy wywołania zamiast konwertować."""
    if md_path.exists() or pdf_tj._gcs_pobierz(md_path):
        return md_path.read_text(encoding="utf-8")
    konwersje.append(md_path.name)
    md_path.write_text("##### Art. 1.\n\nTreść.", encoding="utf-8")
    pdf_tj._gcs_zapisz(md_path)
    return md_path.read_text(encoding="utf-8")


bledy = 0
def sprawdz(warunek, opis):
    global bledy
    print(("ok " if warunek else "ZLE"), opis)
    bledy += 0 if warunek else 1


# (1) bez zmiennej
pdf_tj.GCS_BUCKET, pdf_tj._gcs_bucket_obj = None, None
sprawdz(pdf_tj._gcs() is None, "bez LEGAL_CITE_GCS_BUCKET zasobnik nie jest używany")

# (2)–(3) z atrapą zasobnika
bucket = Bucket()
pdf_tj.GCS_BUCKET, pdf_tj._gcs_bucket_obj = "atrapa", bucket
pdf = pathlib.Path(tempfile.mkdtemp()) / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
inst1 = pathlib.Path(tempfile.mkdtemp())
atrapa_konwersji(pdf, inst1 / "DU_2026_1_abc.md")
sprawdz(konwersje == ["DU_2026_1_abc.md"], "pierwsza instancja konwertuje")
sprawdz("pdf-tj/DU_2026_1_abc.md" in bucket.store, "konwersja trafia do zasobnika")
inst2 = pathlib.Path(tempfile.mkdtemp())
md = atrapa_konwersji(pdf, inst2 / "DU_2026_1_abc.md")
sprawdz(len(konwersje) == 1 and md.startswith("##### Art. 1."), "nowa instancja pobiera z zasobnika, bez konwersji")
txt = inst2 / "DU_2026_1_abc.txt"
if pdf_tj.shutil.which("pdftotext"):
    bucket.store["pdf-tj/DU_2026_1_abc.txt"] = "Art. 1. Treść.".encode()
    sprawdz(pdf_tj._warstwa(pdf, txt) == "Art. 1. Treść.", "warstwa tekstowa też z zasobnika")

# (4) awaria zasobnika
bucket.awaria = True
inst3 = pathlib.Path(tempfile.mkdtemp())
md = atrapa_konwersji(pdf, inst3 / "DU_2026_1_abc.md")
sprawdz(len(konwersje) == 2 and md.startswith("##### Art. 1."), "awaria zasobnika → konwersja, bez wyjątku")

print(f"\n{'wszystko OK' if not bledy else f'{bledy} błędów'}")
sys.exit(1 if bledy else 0)
