# API Manuais de Serviço — Motos

App para mecânicos consultarem manuais de serviço de motocicletas: escolha a moto,
faça a pergunta e receba a resposta com **referências de página do PDF** para abrir
o manual direto no ponto certo. Acesso protegido por login (usuário e senha).

## Como rodar

```powershell
cd C:\Users\scajt\manuais-api
pip install -r requirements.txt
python scripts/ingest.py          # so na primeira vez (ou quando adicionar manuais)
python scripts/create_user.py seu_usuario   # cria o login de acesso (pede a senha)
python -m uvicorn app.main:app --reload
```

Front-end (login + consulta): http://localhost:8000
Documentação interativa (Swagger): http://localhost:8000/docs

## Login e usuários

O acesso ao front e à API (exceto `/auth/login`) exige um cookie de sessão obtido
via login. Cada mecânico tem seu próprio usuário/senha, gravado com hash no SQLite
(`data/index.db`, tabela `users`).

```powershell
python scripts/create_user.py joao      # cria o usuario "joao" (pede senha 2x)
python scripts/create_user.py joao      # rodar de novo com o mesmo nome troca a senha
```

A sessão dura 7 dias (renovando ao fazer login de novo). A chave usada para assinar
o token de sessão fica em `data/.secret_key` (gerada automaticamente na primeira
execução) — pode ser sobrescrita definindo a variável de ambiente `SECRET_KEY`.

## Modo IA (opcional)

Sem chave, o endpoint `/ask` funciona em **modo busca**: devolve as páginas mais
relevantes com trechos. Com a chave do Gemini, ele **responde a pergunta em
português** citando as páginas.

Crie um arquivo `.env` na raiz do projeto (não é versionado) com:

```
GEMINI_API_KEY=sua-chave-aqui
```

A chave é gerada em https://aistudio.google.com/apikey. O `.env` é lido
automaticamente ao subir o servidor (`python-dotenv`), sem precisar configurar
variável de ambiente toda vez.

## Endpoints

Todas as rotas abaixo (exceto login) exigem estar autenticado (cookie de sessão).

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/login` | Body `{"username","password"}` — cria a sessão (cookie) |
| POST | `/auth/logout` | Encerra a sessão |
| GET | `/auth/me` | Usuário logado atual |
| GET | `/manuals` | Lista as motos (filtro opcional `?brand=yamaha`) |
| GET | `/manuals/{id}` | Detalhes de um manual |
| GET | `/manuals/{id}/search?q=...` | Busca full-text, retorna páginas + trechos |
| POST | `/manuals/{id}/ask` | Body `{"question": "..."}` — resposta com referências |
| GET | `/manuals/{id}/pdf` | Serve o PDF (`#page=N` abre na página) |

### Exemplo de uso no front

```js
const res = await fetch("http://localhost:8000/manuals/yamaha-mt07-2016/ask", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question: "qual o torque do parafuso de dreno de oleo?" }),
});
const data = await res.json();
// data.answer  -> resposta em texto (se modo IA)
// data.references -> [{ page, snippet, pdf_url }, ...]
// abrir o PDF na pagina: window.open("http://localhost:8000" + ref.pdf_url)
```

O link `pdf_url` já vem com `#page=N` — navegadores (Chrome/Edge/Firefox) abrem o
PDF direto na página referenciada.

## Manuais

| ID | Moto | Status |
|---|---|---|
| honda-cb600f-hornet-2008 | Honda CB 600F Hornet 2008-2010 | ⚠️ escaneado, precisa de OCR |
| honda-cbr1000rr-2008 | Honda CBR1000RR 2008 | ⚠️ escaneado, precisa de OCR |
| kawasaki-ninja400-2019 | Kawasaki Ninja 400 2019 | ✅ indexado (PT) |
| kawasaki-zx6r-2020 | Kawasaki Ninja ZX-6R 2020 | ✅ indexado (PT) |
| kawasaki-zx10r-2015 | Kawasaki Ninja ZX-10R 2015 | ✅ indexado |
| kawasaki-zx10r-2017 | Kawasaki Ninja ZX-10R 2017 | ✅ indexado (PT) |
| suzuki-hayabusa-2008 | Suzuki GSX 1300R Hayabusa 2008 | ⚠️ escaneado, precisa de OCR |
| suzuki-gsxr1000-2009 | Suzuki GSX-R 1000 2009 | ✅ indexado |
| suzuki-gsxr750-2007 | Suzuki GSX-R 750 2007 | ✅ indexado |
| yamaha-mt09-2015 | Yamaha MT-09 (ABS) 2015 | ✅ indexado |
| yamaha-mt07-2016 | Yamaha MT-07 2016 | ✅ indexado |
| yamaha-r3-2016 | Yamaha YZF-R3 (ABS) 2016 | ✅ indexado |
| yamaha-r1-2007 | Yamaha YZF-R1 2007 | ✅ indexado |
| yamaha-r6s-2007 | Yamaha YZF-R6S 2007 | ✅ indexado |

Os 3 manuais escaneados aparecem em `/manuals` com `searchable: false`; busca e
perguntas neles retornam 422 até serem processados com OCR (próxima etapa).

## Arquitetura

- **Ingestão** (`scripts/ingest.py`): extrai o texto de cada página com PyMuPDF e
  grava no SQLite com índice full-text FTS5 (BM25, sem diacríticos — busca por
  "óleo" e "oleo" funciona igual).
- **Busca** (`app/search.py`): a pergunta vira termos (sem stopwords PT/EN);
  primeiro tenta AND, depois OR; ranking BM25.
- **Perguntas** (`app/rag.py`): recupera as ~8 páginas mais relevantes. Com
  `GEMINI_API_KEY`, o Gemini gera termos de busca no idioma do manual (alguns
  são em inglês), responde em português e cita as páginas usadas `[p. N]`.
- **PDF**: servido pela própria API; o front abre `pdf_url` com `#page=N`.
- **Login** (`app/auth.py`): senha com hash PBKDF2-SHA256, sessão via cookie
  httponly assinado com JWT (7 dias). Usuários ficam na tabela `users` do SQLite;
  gerenciados com `scripts/create_user.py`.
- **Front-end** (`app/static/`): HTML/CSS/JS puro (sem build), servido pela própria
  API — login em `/login`, app em `/`.
