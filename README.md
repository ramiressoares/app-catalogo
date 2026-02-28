# Catálogo de Peixes - Atividade Extensionista ADS

## Objetivo do projeto
O **Catálogo de Peixes** é um sistema web desenvolvido em Flask para apoiar ações extensionistas, permitindo registrar espécies de peixes com foto, nome comum, nome científico, região e descrição.

A proposta é facilitar o levantamento e a divulgação de informações sobre biodiversidade aquática em comunidades, escolas e projetos ambientais.

## Tecnologias utilizadas
- **Python 3**
- **Flask** (backend e renderização de templates)
- **SQLite** (banco de dados local)
- **Bootstrap 5** (interface responsiva, mobile first)
- **HTML/Jinja2**

## Funcionalidades implementadas
- Cadastro de usuários com senha em hash
- Login e logout com controle de sessão
- Proteção de rota: apenas usuário logado cadastra peixes
- Upload de imagem para `static/uploads`
- Campo de imagem compatível com celular:
  - `<input type="file" accept="image/*" capture="environment">`
- Listagem de peixes na página inicial
- Exibição do autor (usuário que cadastrou)
- Ordenação por data mais recente
- Busca por nome comum
- Filtro por região

## Estrutura de pastas
```text
app catalogo/
├── app.py
├── catalogo_peixes.db
├── requirements.txt
├── README.md
├── static/
│   └── uploads/
│       └── .gitkeep
└── templates/
    ├── base.html
    ├── index.html
    ├── add_fish.html
    ├── login.html
    └── register.html
```

## Estrutura do banco de dados
O banco SQLite é criado automaticamente ao iniciar a aplicação.

### Tabela `users`
- `id` (PK)
- `nome`
- `email` (unique)
- `senha` (hash)
- `data_criacao`

### Tabela `peixes`
- `id` (PK)
- `nome_comum`
- `nome_cientifico`
- `regiao`
- `descricao`
- `foto`
- `user_id` (FK para `users.id`)
- `data_postagem`

## Impacto social
Este projeto contribui para a **educação ambiental** e para a **valorização do conhecimento local** sobre espécies aquáticas.

Com o sistema, estudantes e comunidade podem:
- Registrar espécies encontradas em rios, lagos e áreas costeiras
- Produzir um acervo digital colaborativo
- Apoiar atividades de conscientização e preservação ambiental

## Como executar o projeto
1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
2. Execute a aplicação:
   ```bash
   python app.py
   ```
3. Acesse no navegador:
   - `http://127.0.0.1:5000`

## Observações acadêmicas
- O código foi organizado para facilitar leitura e avaliação.
- A função de inicialização cria automaticamente as tabelas necessárias.
- O upload de imagens é salvo em `static/uploads`.
