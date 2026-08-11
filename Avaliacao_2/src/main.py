"""Abre o webmail com Playwright e procura mensagens por palavra-chave."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Locator, Page, TimeoutError, sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
PROFILE_DIR = BASE_DIR / ".playwright-profile"


@dataclass(frozen=True)
class Solicitacao:
    remetente: str
    assunto: str
    resumo: str


def texto(locator: Locator) -> str:
    try:
        return locator.first.inner_text(timeout=2_000).strip()
    except TimeoutError:
        return ""


def aguardar_login(page: Page, seletor_caixa: str) -> None:
    try:
        page.locator(seletor_caixa).first.wait_for(state="visible", timeout=15_000)
    except TimeoutError:
        print("Faça login na janela aberta. Aguardando por até 3 minutos...", flush=True)
        page.locator(seletor_caixa).first.wait_for(state="visible", timeout=180_000)


def buscar_gmail(page: Page, palavra_chave: str) -> list[Solicitacao]:
    print("Abrindo o Gmail...", flush=True)
    page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded")
    seletor = 'input[placeholder*="Pesquisar"], input[placeholder*="Search"]'
    aguardar_login(page, seletor)

    pesquisa = page.locator(seletor).first
    pesquisa.fill(f'is:unread "{palavra_chave}"')
    pesquisa.press("Enter")
    page.wait_for_timeout(3_000)

    solicitacoes: list[Solicitacao] = []
    linhas = page.locator('tr[role="main"]')
    for indice in range(linhas.count()):
        linha = linhas.nth(indice)
        remetente = linha.locator("span[email]").first
        solicitacoes.append(
            Solicitacao(
                remetente=remetente.get_attribute("email") or texto(remetente),
                assunto=texto(linha.locator("span.bog")),
                resumo=texto(linha.locator("span.y2")).lstrip(" -\u00a0"),
            )
        )
    return solicitacoes


def buscar_outlook(page: Page, palavra_chave: str) -> list[Solicitacao]:
    print("Abrindo o Outlook...", flush=True)
    page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded")
    seletor = '[aria-label*="Pesquisar"], [aria-label*="Search"]'
    aguardar_login(page, seletor)

    pesquisa = page.locator(seletor).first
    pesquisa.fill(palavra_chave)
    pesquisa.press("Enter")
    page.wait_for_timeout(3_000)

    solicitacoes: list[Solicitacao] = []
    linhas = page.locator(
        '[role="option"][aria-label*="Não lida"], '
        '[role="option"][aria-label*="Unread"]'
    )
    for indice in range(linhas.count()):
        conteudo = texto(linhas.nth(indice))
        if palavra_chave.casefold() not in conteudo.casefold():
            continue
        partes = [parte.strip() for parte in re.split(r"\r?\n", conteudo) if parte.strip()]
        solicitacoes.append(
            Solicitacao(
                remetente=partes[0] if partes else "",
                assunto=next(
                    (p for p in partes if palavra_chave.casefold() in p.casefold()),
                    palavra_chave,
                ),
                resumo=" | ".join(partes[1:]),
            )
        )
    return solicitacoes


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    provedor = os.getenv("EMAIL_PROVIDER", "gmail").strip().lower()
    palavra_chave = os.getenv("EMAIL_KEYWORD", "cadastro").strip()
    canal = os.getenv("BROWSER_CHANNEL", "chrome").strip().lower()
    headless = os.getenv("HEADLESS", "false").strip().lower() == "true"

    if provedor not in {"gmail", "outlook"}:
        raise ValueError("EMAIL_PROVIDER deve ser gmail ou outlook.")
    if not palavra_chave:
        raise ValueError("EMAIL_KEYWORD não pode ficar vazio.")

    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        contexto = playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel=canal,
            headless=headless,
            locale="pt-BR",
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            contexto.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
            buscar = buscar_gmail if provedor == "gmail" else buscar_outlook
            solicitacoes = buscar(pagina, palavra_chave)

            print(f"Busca concluída: {len(solicitacoes)} mensagem(ns) encontrada(s).")
            for numero, solicitacao in enumerate(solicitacoes, start=1):
                print(f"\n{numero}. {solicitacao.assunto}")
                print(f"   Remetente: {solicitacao.remetente}")
                print(f"   Resumo: {solicitacao.resumo}")

            if not headless:
                input("\nPressione Enter para fechar o navegador...")
        finally:
            contexto.close()


if __name__ == "__main__":
    main()
