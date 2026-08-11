"""Busca e-mails no Gmail via IMAP e baixa anexos PDF."""

from __future__ import annotations

import imaplib
import os
import re
import socket
import time
import unicodedata
from io import BytesIO
from itertools import product
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

from validacao import validar_documentos
from planilha import atualizar_planilha


BASE_DIR = Path(__file__).resolve().parents[1]
PASTA_DOCUMENTOS = BASE_DIR / "Documentos_OK"
PASTA_PENDENTES = BASE_DIR / "Documentos_Pendentes"


def decodificar(valor: str | None) -> str:
    return str(make_header(decode_header(valor))) if valor else ""


def normalizar(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto).casefold()
        if not unicodedata.combining(c)
    )


def extrair_texto(mensagem: Message) -> str:
    partes = mensagem.walk() if mensagem.is_multipart() else [mensagem]
    textos: list[str] = []
    for parte in partes:
        if parte.get_content_disposition() == "attachment":
            continue
        if parte.get_content_type() not in {"text/plain", "text/html"}:
            continue
        conteudo = parte.get_payload(decode=True)
        if conteudo:
            charset = parte.get_content_charset() or "utf-8"
            textos.append(conteudo.decode(charset, errors="replace"))
    return "\n".join(textos)


def nome_disponivel(diretorio: Path, nome: str) -> Path:
    nome = re.sub(r'[<>:"/\\|?*]', "_", Path(nome).name).strip() or "anexo.pdf"
    destino = diretorio / nome
    contador = 1
    while destino.exists():
        destino = diretorio / f"{Path(nome).stem}_{contador}{Path(nome).suffix}"
        contador += 1
    return destino


def baixar_pdfs(mensagem: Message) -> tuple[list[Path], bool]:
    anexos: list[tuple[str, bytes, str]] = []
    for parte in mensagem.walk():
        nome = decodificar(parte.get_filename())
        if not nome.lower().endswith(".pdf"):
            continue
        conteudo = parte.get_payload(decode=True)
        if not conteudo:
            continue
        try:
            leitor = PdfReader(BytesIO(conteudo))
            texto = normalizar("\n".join(pagina.extract_text() or "" for pagina in leitor.pages))
        except Exception as erro:
            print(f"PDF ignorado por não ser legível: {nome} ({erro})", flush=True)
            continue
        anexos.append((nome, conteudo, texto))

    candidatos: dict[str, list[int]] = {"nome": [], "cpf": [], "endereco": []}
    for indice, (_, _, texto) in enumerate(anexos):
        if re.search(r"\bnome\s*:", texto):
            candidatos["nome"].append(indice)
        if re.search(r"\bcpf\s*:|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", texto):
            candidatos["cpf"].append(indice)
        if re.search(r"\bendereco\s*:", texto):
            candidatos["endereco"].append(indice)

    selecionados: tuple[int, int, int] | None = None
    for combinacao in product(
        candidatos["nome"], candidatos["cpf"], candidatos["endereco"]
    ):
        if len(set(combinacao)) == 3:
            selecionados = combinacao
            break

    if selecionados is None:
        ausentes = [tipo for tipo, itens in candidatos.items() if not itens]
        detalhe = ", ".join(ausentes) if ausentes else "três arquivos distintos"
        print(
            "Conjunto incompleto. Os PDFs serão enviados para Documentos_Pendentes. "
            f"Requisito ausente: {detalhe}.",
            flush=True,
        )
        PASTA_PENDENTES.mkdir(parents=True, exist_ok=True)
        arquivos_pendentes: list[Path] = []
        for nome, conteudo, _ in anexos:
            destino = nome_disponivel(PASTA_PENDENTES, nome)
            destino.write_bytes(conteudo)
            arquivos_pendentes.append(destino)
            print(f"PDF pendente salvo: {destino}", flush=True)
        return arquivos_pendentes, False

    arquivos: list[Path] = []
    for indice in selecionados:
        nome, conteudo, _ = anexos[indice]
        destino = nome_disponivel(PASTA_DOCUMENTOS, nome)
        destino.write_bytes(conteudo)
        arquivos.append(destino)
        print(f"PDF salvo: {destino}", flush=True)
    return arquivos, True


def buscar_e_baixar(email: str, senha_app: str, palavra_chave: str) -> tuple[int, int]:
    palavra_normalizada = normalizar(palavra_chave)
    palavras = re.findall(r"\w+", palavra_normalizada)
    palavra_base = max(palavras, key=len, default="cadastro")
    consulta = f'"is:unread has:attachment {palavra_base}"'.encode("ascii")
    total = 0
    total_pendentes = 0

    print("Conectando ao Gmail por IMAP...", flush=True)
    with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20) as caixa:
        caixa.login(email, senha_app.replace(" ", ""))
        print("Login realizado. Procurando mensagens...", flush=True)
        status, _ = caixa.select("INBOX")
        if status != "OK":
            raise RuntimeError("Não foi possível abrir a caixa de entrada.")

        status, resultado = caixa.search(None, "X-GM-RAW", consulta)
        if status != "OK":
            raise RuntimeError("O Gmail recusou a pesquisa IMAP.")

        ids = resultado[0].split()
        print(f"{len(ids)} mensagem(ns) candidata(s) encontrada(s).", flush=True)
        for identificador in ids:
            status, dados = caixa.fetch(identificador, "(BODY.PEEK[])")
            if status != "OK" or not dados or not isinstance(dados[0], tuple):
                continue
            mensagem = message_from_bytes(dados[0][1])
            assunto = decodificar(mensagem.get("Subject"))
            pesquisavel = normalizar(assunto + "\n" + extrair_texto(mensagem))
            if palavra_normalizada not in pesquisavel:
                continue

            print(f"Processando: {assunto or '(sem assunto)'}", flush=True)
            arquivos, conjunto_completo = baixar_pdfs(mensagem)
            if conjunto_completo:
                total += len(arquivos)
            else:
                total_pendentes += len(arquivos)
            if arquivos:
                caixa.store(identificador, "+FLAGS", "\\Seen")
    return total, total_pendentes


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    email = os.getenv("EMAIL", "").strip()
    senha_app = os.getenv("EMAIL_APP_PASSWORD", "").strip()
    palavra_chave = os.getenv("EMAIL_KEYWORD", "cadastro").strip()

    if not email or not senha_app:
        raise SystemExit("Defina EMAIL e EMAIL_APP_PASSWORD no arquivo .env.")
    if not palavra_chave:
        raise SystemExit("EMAIL_KEYWORD não pode ficar vazio.")

    PASTA_DOCUMENTOS.mkdir(parents=True, exist_ok=True)
    try:
        total, total_pendentes = buscar_e_baixar(email, senha_app, palavra_chave)
    except imaplib.IMAP4.error as erro:
        raise SystemExit(f"Falha na autenticação ou operação IMAP: {erro}") from erro
    except (TimeoutError, socket.timeout) as erro:
        raise SystemExit("A conexão IMAP excedeu o limite de 20 segundos.") from erro
    except OSError as erro:
        raise SystemExit(f"Não foi possível conectar ao Gmail: {erro}") from erro

    print(f"Download concluído: {total} arquivo(s) PDF salvo(s).")
    print(f"Documentos pendentes: {total_pendentes} arquivo(s) PDF salvo(s).")
    if total:
        resultado = validar_documentos(PASTA_DOCUMENTOS)
        situacao = "APROVADA" if resultado.aprovado else "REPROVADA"
        print(f"Validação dos documentos: {situacao}.")
        print(f"Relatório: {PASTA_DOCUMENTOS / 'resultado_validacao.txt'}")
        if resultado.aprovado:
            linhas = atualizar_planilha(
                BASE_DIR / "Planilha_Mestra.xlsx", PASTA_DOCUMENTOS
            )
            print(f"Planilha mestra atualizada nas linhas: {linhas}.")
    print("Encerrando em 3 segundos...", flush=True)
    time.sleep(3)


if __name__ == "__main__":
    main()
