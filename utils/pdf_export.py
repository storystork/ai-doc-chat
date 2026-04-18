"""
utils/pdf_export.py – Export chat messages to a PDF using ReportLab.
"""
from typing import Any, Dict, List
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_RIGHT


def export_chat_to_pdf_bytes(chat_title: str, messages: List[Dict[str, Any]]) -> bytes:
    """
    Convert a list of chat messages into a PDF and return raw bytes.

    Each message dict should have at least: { role: str, content: str }
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ChatTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6,
    )
    user_style = ParagraphStyle(
        "UserMsg",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1e40af"),
        leftIndent=40,
        alignment=TA_RIGHT,
        spaceAfter=6,
        spaceBefore=4,
    )
    ai_style = ParagraphStyle(
        "AIMsg",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6,
        spaceBefore=4,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=2,
    )

    story = []

    story.append(Paragraph(chat_title or "Chat Export", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 0.4 * cm))

    for msg in messages:
        role = (msg.get("role") or "unknown").lower()
        content = (msg.get("content") or "").replace("\n", "<br/>")
        timestamp = (msg.get("created_at") or "")[:16].replace("T", " ")

        if role == "user":
            story.append(Paragraph(f"<b>You</b>  <font size='7' color='#94a3b8'>{timestamp}</font>", label_style))
            story.append(Paragraph(content, user_style))
        else:
            story.append(Paragraph(f"<b>AI</b>  <font size='7' color='#94a3b8'>{timestamp}</font>", label_style))
            story.append(Paragraph(content, ai_style))

        story.append(Spacer(1, 0.15 * cm))

    doc.build(story)
    return buffer.getvalue()