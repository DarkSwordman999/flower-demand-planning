# -*- coding: utf-8 -*-
"""Формулы в отчётах: LaTeX → формула Word (OMML).

LaTeX переводится в MathML пакетом latex2mathml, MathML в OMML —
таблицей стилей MML2OMML.XSL, которая входит в состав MS Word."""
import glob, re
from functools import lru_cache
from lxml import etree
import latex2mathml.converter

_XSL_GLOBS = [
    r"C:\Program Files\Microsoft Office\root\Office*\MML2OMML.XSL",
    r"C:\Program Files (x86)\Microsoft Office\root\Office*\MML2OMML.XSL",
    r"C:\Program Files\Microsoft Office\Office*\MML2OMML.XSL",
    r"C:\Program Files (x86)\Microsoft Office\Office*\MML2OMML.XSL",
]
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_FUNCS = re.compile(r"\\(min|max|ln|log|exp)(?![A-Za-z])")


@lru_cache(maxsize=1)
def _xslt():
    for g in _XSL_GLOBS:
        found = sorted(glob.glob(g))
        if found:
            return etree.XSLT(etree.parse(found[-1]))
    raise FileNotFoundError("Не найден MML2OMML.XSL из состава MS Word")


def omml(latex, size=14, display=False):
    """Элемент m:oMath для формулы в LaTeX; шрифт Cambria Math нужного кегля."""
    latex = _FUNCS.sub(r"\\mathrm{\1}", latex)  # имена функций — прямым шрифтом
    mml = latex2mathml.converter.convert(latex, display="block" if display else "inline")
    om = _xslt()(etree.fromstring(mml.encode("utf-8"))).getroot()
    if om.tag != f"{{{M_NS}}}oMath":
        om = om.find(f".//{{{M_NS}}}oMath")
    # пределы суммы: в отдельной строке — над и под знаком, внутри строки текста — справа
    for nary in om.iter(f"{{{M_NS}}}nary"):
        pr = nary.find(f"{{{M_NS}}}naryPr")
        if pr is None:
            pr = etree.Element(f"{{{M_NS}}}naryPr")
            nary.insert(0, pr)
        loc = pr.find(f"{{{M_NS}}}limLoc")
        if loc is None:
            loc = etree.Element(f"{{{M_NS}}}limLoc")
            pr.insert(1 if pr.find(f"{{{M_NS}}}chr") is not None else 0, loc)
        loc.set(f"{{{M_NS}}}val", "undOvr" if display else "subSup")
    half_pt = str(int(size * 2))
    for r in om.iter(f"{{{M_NS}}}r"):
        rpr = r.find(f"{{{W_NS}}}rPr")
        if rpr is None:  # w:rPr стоит после m:rPr и перед m:t
            rpr = etree.Element(f"{{{W_NS}}}rPr")
            r.insert(0 if r.find(f"{{{M_NS}}}rPr") is None else 1, rpr)
        for tag in ("rFonts", "sz", "szCs"):
            old = rpr.find(f"{{{W_NS}}}{tag}")
            if old is not None:
                rpr.remove(old)
        f = etree.SubElement(rpr, f"{{{W_NS}}}rFonts")
        for a in ("ascii", "hAnsi", "cs"):
            f.set(f"{{{W_NS}}}{a}", "Cambria Math")
        etree.SubElement(rpr, f"{{{W_NS}}}sz").set(f"{{{W_NS}}}val", half_pt)
        etree.SubElement(rpr, f"{{{W_NS}}}szCs").set(f"{{{W_NS}}}val", half_pt)
    return om


def add_inline(paragraph, latex, size=14):
    """Формула внутри абзаца или ячейки таблицы."""
    from docx.oxml import parse_xml
    paragraph._p.append(parse_xml(etree.tostring(omml(latex, size))))


def add_display(paragraph, latex, size=14):
    """Отдельная строка с формулой по центру (m:oMathPara)."""
    from docx.oxml import parse_xml
    para = etree.Element(f"{{{M_NS}}}oMathPara", nsmap={"m": M_NS})
    para.append(omml(latex, size, display=True))
    paragraph._p.append(parse_xml(etree.tostring(para)))
