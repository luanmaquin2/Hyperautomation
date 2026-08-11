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


def linhas_gmail(page: Page, palavra_chave: str) -> Locator:
    """Localiza as linhas pelo texto, inclusive quando o remetente aparece como 'eu'."""
    return page.locator("tr").filter(has_text=re.compile(re.escape(palavra_chave), re.I))


def buscar_gmail(page: Page, palavra_chave: str) -> list[Solicitacao]:
    print("Abrindo o Gmail...", flush=True)
    page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded")
    seletor = 'input[placeholder*="Pesquisar"], input[placeholder*="Search"]'
    aguardar_login(page, seletor)

    pesquisa = page.locator(seletor).first
    pesquisa.fill(f'is:unread "{palavra_chave}"')
    pesquisa.press("Enter")
    page.wait_for_timeout(2_000)

    solicitacoes: list[Solicitacao] = []
    linhas = linhas_gmail(page, palavra_chave)
    try:
        linhas.first.wait_for(state="visible", timeout=15_000)
    except TimeoutError:
        # A ausência de linhas também é um resultado válido da pesquisa.
        print(
            f'O Gmail não apresentou uma linha contendo "{palavra_chave}".',
            flush=True,
        )
        return solicitacoes

    print(f"Linhas de e-mail localizadas: {linhas.count()}.", flush=True)
    for indice in range(linhas.count()):
        linha = linhas.nth(indice)
        remetente = linha.locator("span[email]").first
        remetente_email = remetente.get_attribute("email") if remetente.count() else ""
        assunto = texto(linha.locator("span.bog"))
        conteudo_linha = " ".join(texto(linha).split())
        solicitacoes.append(
            Solicitacao(
                remetente=(
                    remetente_email
                    or texto(remetente)
                    or "Remetente não informado"
                ),
                assunto=assunto or conteudo_linha,
                resumo=texto(linha.locator("span.y2")).lstrip(" -\u00a0"),
            )
        )
    return solicitacoes


def nome_disponivel(diretorio: Path, nome: str) -> Path:
    nome_limpo = re.sub(r'[<>:"/\\|?*]', "_", Path(nome).name).strip()
    destino = diretorio / (nome_limpo or "anexo.pdf")
    contador = 1
    while destino.exists():
        destino = diretorio / f"{Path(nome_limpo).stem}_{contador}{Path(nome_limpo).suffix}"
        contador += 1
    return destino


def baixar_anexos_gmail(
    page: Page,
    solicitacoes: list[Solicitacao],
    diretorio: Path,
    palavra_chave: str,
) -> int:
    diretorio.mkdir(parents=True, exist_ok=True)
    total = 0

    # Processa de baixo para cima. Ao abrir uma mensagem, o Gmail pode marcá-la
    # como lida e removê-la dos resultados da pesquisa "is:unread".
    for indice_email in range(len(solicitacoes) - 1, -1, -1):
        numero = len(solicitacoes) - indice_email
        linhas = linhas_gmail(page, palavra_chave)
        if linhas.count() <= indice_email:
            print(f"E-mail {numero}: a linha não está mais disponível.", flush=True)
            continue

        print(
            f"Entrando no e-mail {numero}/{len(solicitacoes)} para buscar anexos...",
            flush=True,
        )
        linha = linhas.nth(indice_email)
        assunto = linha.locator("span.bog")
        if assunto.count() > 0:
            assunto.first.click()
        else:
            linha.click()
        try:
            page.locator("h2.hP").first.wait_for(state="visible", timeout=15_000)
        except TimeoutError:
            print(f"E-mail {numero}: não foi possível abrir a mensagem.", flush=True)
            page.go_back(wait_until="domcontentloaded")
            continue

        anexos = page.locator("span.aV3")
        for indice in range(anexos.count()):
            nome_exibido = texto(anexos.nth(indice)) or "anexo"
            bloco = anexos.nth(indice).locator(
                "xpath=ancestor::div[contains(@class, 'aQH')][1]"
            )
            bloco.hover()
            page.wait_for_timeout(500)

            botoes = bloco.locator(
                '.aQv, [aria-label*="download" i], [aria-label*="baixar" i], '
                '[data-tooltip*="download" i], [data-tooltip*="baixar" i]'
            )
            if botoes.count() == 0:
                # Algumas versões do Gmail posicionam a ação fora do bloco
                # visual do anexo. Nesse caso, procura pelo nome do arquivo.
                botoes = page.locator(
                    '[aria-label*="download" i], [aria-label*="baixar" i], '
                    '[data-tooltip*="download" i], [data-tooltip*="baixar" i]'
                ).filter(has_text=re.compile(re.escape(nome_exibido), re.I))

            if botoes.count() == 0:
                print(f"Botão de download não localizado: {nome_exibido}", flush=True)
                continue

            botao = botoes.last
            try:
                with page.expect_download(timeout=15_000) as evento:
                    botao.click(force=True)
                download = evento.value
                destino = nome_disponivel(
                    diretorio, download.suggested_filename or nome_exibido
                )
                download.save_as(destino)
                total += 1
                print(f"Anexo salvo: {destino}", flush=True)
            except TimeoutError:
                print(
                    f"O botão foi clicado, mas o download não iniciou: {nome_exibido}",
                    flush=True,
                )

        if anexos.count() == 0:
            print(f"E-mail {numero}: nenhum anexo encontrado.", flush=True)

        page.go_back(wait_until="domcontentloaded")
        page.wait_for_timeout(1_500)

    return total


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
    pasta_download = BASE_DIR / "Documentos_OK"

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
            accept_downloads=True,
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

            if provedor == "gmail" and solicitacoes:
                baixados = baixar_anexos_gmail(
                    pagina, solicitacoes, pasta_download, palavra_chave
                )
                print(f"\nDownload concluído: {baixados} anexo(s) salvo(s).")
            elif provedor == "outlook" and solicitacoes:
                print("O download automático de anexos está disponível para Gmail.")

            if not headless:
                input("\nPressione Enter para fechar o navegador...")
        finally:
            contexto.close()


if __name__ == "__main__":
    main()
