# Busca de e-mails com Playwright

Abre Gmail ou Outlook no navegador e procura mensagens não lidas usando uma
palavra-chave configurada no `.env`.

## Instalação

```powershell
cd Avaliacao_2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuração

Crie o arquivo `.env` baseado no `.env.example`:

```env
EMAIL_PROVIDER=gmail
EMAIL_KEYWORD=cadastro
BROWSER_CHANNEL=chrome
HEADLESS=false
```

`EMAIL_PROVIDER` aceita `gmail` ou `outlook`. A senha de app não é usada pelo
Playwright, pois ela funciona com IMAP e não com o login web.

## Execução

```powershell
python src/main.py
```

Na primeira execução, faça login na janela aberta. A sessão ficará armazenada
em `.playwright-profile`. Nas execuções seguintes, o navegador reutilizará esse
login. Depois da busca, os e-mails encontrados são abertos e todos os seus anexos
são salvos em `Avaliacao_2/Documentos_OK`. A pasta é criada automaticamente.
Como os e-mails são abertos para acessar os anexos, o Gmail pode marcá-los como
lidos.
