from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import fitz


@dataclass
class FixtureField:
    label: str
    name: str
    x: float
    y: float
    width: float
    height: float = 20.0
    value: str = ""


DEFAULT_FIELDS: Sequence[FixtureField] = (
    FixtureField("Policy Number", "Field1", 190, 720, 220),
    FixtureField("Insured Name", "Field2", 190, 680, 220),
    FixtureField("Incident Date", "Field3", 190, 640, 180),
)


def create_flat_template_pdf(path: Path, fields: Iterable[FixtureField] = DEFAULT_FIELDS) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _draw_header(page, "Vehicle Incident Report")
    for field in fields:
        _draw_labeled_box(page, field)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def create_flat_filled_pdf(path: Path, fields: Iterable[FixtureField]) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _draw_header(page, "Vehicle Incident Report")
    for field in fields:
        _draw_labeled_box(page, field)
        if field.value:
            page.insert_text(
                fitz.Point(field.x + 8, field.y + 15),
                field.value,
                fontsize=10,
                fontname="helv",
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def create_turkish_student_petition_template_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(fitz.Point(72, 48), "ÖĞRENCİ DİLEKÇE FORMU", fontsize=17, fontname="helv")
    page.insert_text(fitz.Point(72, 64), "STUDENT PETITION FORM", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(72, 120), "Öğrenci Bilgileri / Student's Information", fontsize=12, fontname="helv")

    _draw_labeled_line(page, "Tarih", 395, 140, 120)
    _draw_labeled_line(page, "Öğrenci No", 72, 175, 200)
    _draw_labeled_line(page, "T.C. Kimlik No", 72, 210, 220)
    _draw_labeled_line(page, "Ad Soyad", 72, 245, 220)
    _draw_labeled_line(page, "Bölüm/Program", 72, 280, 220)
    _draw_labeled_line(page, "Cep Telefon No", 72, 315, 220)
    _draw_labeled_line(page, "E-Posta Adresi", 72, 350, 260)
    _draw_labeled_line(page, "GANO", 360, 315, 120)
    _draw_labeled_line(page, "Tamamlanan Kredi", 360, 350, 120)

    page.insert_text(fitz.Point(72, 410), "Ders Kodu", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(168, 410), "Dersin Adı", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(354, 410), "Dersin Kredisi", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(472, 410), "AKTS", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(530, 410), "Ders Notu", fontsize=10, fontname="helv")
    page.draw_rect(fitz.Rect(72, 420, 520, 450), width=0.8)
    for x in (160, 350, 465, 525):
        page.draw_line(fitz.Point(x, 420), fitz.Point(x, 450))

    page.insert_text(fitz.Point(72, 500), "Öğrencinin Açıklaması / Student's Explanation", fontsize=12, fontname="helv")
    for y in (520, 548, 576, 604):
        page.draw_line(fitz.Point(72, y), fitz.Point(523, y))

    page.insert_text(fitz.Point(72, 665), "Öğretim Üyesi/Danışman Görüşü", fontsize=12, fontname="helv")
    for y in (685, 713, 741):
        page.draw_line(fitz.Point(72, y), fitz.Point(523, y))

    page.insert_text(fitz.Point(72, 785), "Öğrencinin İmzası", fontsize=10, fontname="helv")
    page.draw_line(fitz.Point(170, 790), fitz.Point(430, 790))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def create_single_course_application_template_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(fitz.Point(160, 66), "TEK DERS BAŞVURU FORMU", fontsize=14, fontname="helv")
    _draw_labeled_line(page, "Tarih", 430, 140, 120)
    page.insert_text(fitz.Point(195, 170), "Fakültesi/MYO Müdürlüğü'ne", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(56, 205), "..... numara ile kayıtlı öğrencinizim.", fontsize=9, fontname="helv")
    page.insert_text(fitz.Point(360, 187), "Bölümüne/Programına", fontsize=9, fontname="helv")
    page.insert_text(fitz.Point(56, 256), "Adı ve Soyadı", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(56, 272), "Tel No / E-posta", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(56, 288), "Adres", fontsize=10, fontname="helv")
    for y in (260, 276, 292, 307):
        page.draw_line(fitz.Point(146, y), fitz.Point(476, y))
    page.insert_text(fitz.Point(445, 325), "İmzası", fontsize=9, fontname="helv")
    page.draw_rect(fitz.Rect(56, 352, 524, 420), width=0.8)
    for x in (96, 145, 317, 431, 476):
        page.draw_line(fitz.Point(x, 352), fitz.Point(x, 420))
    page.insert_text(fitz.Point(105, 368), "Ders Kodu", fontsize=8, fontname="helv")
    page.insert_text(fitz.Point(205, 368), "Dersin Adı", fontsize=8, fontname="helv")
    page.insert_text(fitz.Point(340, 368), "Dersin Kredisi", fontsize=8, fontname="helv")
    page.insert_text(fitz.Point(438, 368), "Dersin AKTS'si", fontsize=8, fontname="helv")
    page.insert_text(fitz.Point(486, 368), "Dersin Notu", fontsize=8, fontname="helv")
    page.insert_text(fitz.Point(40, 438), "Danışmanın Adı", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(145, 441), fitz.Point(476, 441))
    page.insert_text(fitz.Point(40, 459), "Danışmanın açıklamalı görüşü", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(188, 462), fitz.Point(476, 462))
    page.insert_text(fitz.Point(40, 480), "GNO", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(108, 483), fitz.Point(176, 483))
    page.insert_text(fitz.Point(40, 500), "Öğrencinin dönem sayısı", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(137, 503), fitz.Point(176, 503))
    page.draw_line(fitz.Point(37, 535), fitz.Point(121, 535))
    page.insert_text(fitz.Point(260, 560), "Mali Onay", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(260, 587), "Ödenen Ders ve Kredi/AKTS Sayısı", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(411, 590), fitz.Point(475, 590))
    page.insert_text(fitz.Point(260, 606), "Adı Soyadı", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(347, 609), fitz.Point(477, 609))
    page.insert_text(fitz.Point(260, 630), "Tarih ve İmza", fontsize=8, fontname="helv")
    page.draw_line(fitz.Point(347, 633), fitz.Point(530, 633))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def create_reportlab_acroform_pdf(
    path: Path, fields: Iterable[FixtureField] = DEFAULT_FIELDS
) -> Path:
    try:
        from reportlab.lib.colors import black
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab is required to create AcroForm fixtures.") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    page_width = 595
    page_height = 842
    pdf = canvas.Canvas(str(path), pagesize=(page_width, page_height))
    pdf.setTitle("Vehicle Incident Report")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, 790, "Vehicle Incident Report")
    pdf.setFont("Helvetica", 10)
    form = pdf.acroForm
    for field in fields:
        reportlab_y = page_height - field.y - field.height
        pdf.drawString(72, reportlab_y + 6, field.label)
        form.textfield(
            name=field.name,
            tooltip=field.label,
            x=field.x,
            y=reportlab_y,
            width=field.width,
            height=field.height,
            borderStyle="underlined",
            borderWidth=1,
            borderColor=black,
            forceBorder=True,
            value=field.value,
        )
    pdf.save()
    return path


def _draw_header(page: fitz.Page, title: str) -> None:
    page.insert_text(fitz.Point(72, 60), title, fontsize=18, fontname="helv")
    page.draw_line(fitz.Point(72, 72), fitz.Point(520, 72))


def _draw_labeled_box(page: fitz.Page, field: FixtureField) -> None:
    page.insert_text(fitz.Point(72, field.y + 15), field.label, fontsize=10, fontname="helv")
    rect = fitz.Rect(field.x, field.y, field.x + field.width, field.y + field.height)
    page.draw_rect(rect, width=0.8)


def _draw_labeled_line(page: fitz.Page, label: str, x: float, y: float, width: float) -> None:
    page.insert_text(fitz.Point(x, y), label, fontsize=10, fontname="helv")
    page.draw_line(fitz.Point(x + 98, y + 4), fitz.Point(x + 98 + width, y + 4))
