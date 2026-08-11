"""Valida se os PDFs obrigatórios foram baixados e podem ser lidos."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class ResultadoValidacao:
    aprovado: bool
    mensagens: list[str]


def _normalizar(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto).casefold()
        if not unicodedata.combining(c)
    )


def validar_documentos(diretorio: Path) -> ResultadoValidacao:
    mensagens: list[str] = []
    tipos: set[str] = set()
    pdfs = sorted(diretorio.glob("*.pdf"))

    for arquivo in pdfs:
        nome = _normalizar(arquivo.stem)
        if "identidade" in nome or "rg" in nome:
            tipos.add("identidade")
        if "cpf" in nome:
            tipos.add("cpf")
        if "residencia" in nome or "endereco" in nome:
            tipos.add("comprovante de residência")
        try:
            leitor = PdfReader(arquivo)
            if not leitor.pages:
                raise ValueError("PDF sem páginas")
            mensagens.append(f"OK: {arquivo.name} é legível.")
        except Exception as erro:
            mensagens.append(f"ERRO: {arquivo.name} não é legível ({erro}).")

    for ausente in sorted({"identidade", "cpf", "comprovante de residência"} - tipos):
        mensagens.append(f"ERRO: documento obrigatório ausente: {ausente}.")
    if not pdfs:
        mensagens.append("ERRO: nenhum PDF encontrado.")

    aprovado = not any(item.startswith("ERRO:") for item in mensagens)
    titulo = "VALIDAÇÃO APROVADA" if aprovado else "VALIDAÇÃO REPROVADA"
    (diretorio / "resultado_validacao.txt").write_text(
        titulo + "\n\n" + "\n".join(mensagens), encoding="utf-8"
    )
    return ResultadoValidacao(aprovado, mensagens)
