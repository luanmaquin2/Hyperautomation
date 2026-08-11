# Busca de PDFs no Gmail por IMAP

O programa acessa o Gmail sem navegador, procura mensagens não lidas com a
palavra-chave configurada e salva os anexos PDF em `Documentos_OK`.

## Configuração

Instale as dependências:

```powershell
pip install -r requirements.txt
```

Crie o `.env`:

```env
EMAIL=seu_email@gmail.com
EMAIL_APP_PASSWORD=sua_senha_de_app
EMAIL_KEYWORD=cadastro avaliacao 2
```

A senha deve ser uma senha de app do Google, não a senha normal. A conta precisa
ter verificação em duas etapas. Mensagens processadas com pelo menos um PDF são
marcadas como lidas para não serem baixadas novamente.

## Execução

```powershell
python src/main.py
```
