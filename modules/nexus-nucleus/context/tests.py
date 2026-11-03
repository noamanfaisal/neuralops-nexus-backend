"""
Context sources — text extraction from attached files (context/services.py).

Found live 2026-11-02 (Contabo): the extraction code for PDF and Word existed,
but pypdf and python-docx were never installed, so every PDF/DOCX attached in
chat ended in status=error ("pypdf not installed"). These tests build a real
PDF and a real .docx in memory and read them back through the same function
the attach flow uses — a missing library fails here, not in front of a user.
"""
from io import BytesIO

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from context.services import _extract_file_content


def _tiny_pdf(text: str) -> bytes:
    """A minimal, valid one-page PDF whose page shows `text` (Helvetica)."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


class ExtractFileContentTests(SimpleTestCase):
    def test_pdf_text_is_extracted(self):
        f = ContentFile(_tiny_pdf("Quarterly dashboard answers"), name="Dashboard answers.pdf")
        text = _extract_file_content(f, "Dashboard answers.pdf")
        self.assertIn("Quarterly dashboard answers", text)

    def test_docx_text_is_extracted(self):
        import docx
        document = docx.Document()
        document.add_paragraph("Revenue grew 12 percent")
        document.add_paragraph("Churn fell to 3 percent")
        buffer = BytesIO()
        document.save(buffer)
        f = ContentFile(buffer.getvalue(), name="report.docx")
        text = _extract_file_content(f, "report.docx")
        self.assertIn("Revenue grew 12 percent", text)
        self.assertIn("Churn fell to 3 percent", text)

    def test_plain_text_still_reads_as_text(self):
        f = ContentFile("hello from a markdown file".encode(), name="notes.md")
        self.assertEqual(_extract_file_content(f, "notes.md"), "hello from a markdown file")
