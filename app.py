import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from typing import List
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


# Caminhos principais do projeto
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "catalogo_peixes.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

# Extensões de imagem permitidas para upload
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
DELETE_WINDOW_MINUTES = 20
ADMIN_USER_IDS = {1}
ADMIN_EMAILS = {email.strip().lower() for email in os.getenv("ADMIN_EMAILS", "").split(",") if email.strip()}


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.secret_key = "catalogo-peixes-secret"


def get_db_connection() -> sqlite3.Connection:
	"""Cria conexão com SQLite, habilitando FK e retorno por chave de coluna."""
	conn = sqlite3.connect(DB_PATH)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA foreign_keys = ON")
	return conn


def ensure_table_schema(conn: sqlite3.Connection, table_name: str, required_columns: List[str], create_sql: str) -> None:
	"""Garante esquema esperado; se estiver inconsistente, recria a tabela."""
	existing = conn.execute(
		"SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
	).fetchone()

	if not existing:
		conn.execute(create_sql)
		return

	cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
	existing_columns = {col[1] for col in cols}

	if set(required_columns) != existing_columns:
		conn.execute(f"DROP TABLE IF EXISTS {table_name}")
		conn.execute(create_sql)


def init_db() -> None:
	"""Cria pasta de upload e estrutura do banco automaticamente."""
	os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

	users_columns = ["id", "nome", "email", "senha", "data_criacao"]
	peixes_columns = [
		"id",
		"nome_comum",
		"nome_cientifico",
		"regiao",
		"descricao",
		"foto",
		"user_id",
		"data_postagem",
	]

	create_users_sql = """
	CREATE TABLE IF NOT EXISTS users (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		nome TEXT NOT NULL,
		email TEXT NOT NULL UNIQUE,
		senha TEXT NOT NULL,
		data_criacao TEXT NOT NULL
	)
	"""

	create_peixes_sql = """
	CREATE TABLE IF NOT EXISTS peixes (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		nome_comum TEXT NOT NULL,
		nome_cientifico TEXT NOT NULL,
		regiao TEXT NOT NULL,
		descricao TEXT NOT NULL,
		foto TEXT NOT NULL,
		user_id INTEGER NOT NULL,
		data_postagem TEXT NOT NULL,
		FOREIGN KEY (user_id) REFERENCES users(id)
	)
	"""

	with get_db_connection() as conn:
		ensure_table_schema(conn, "users", users_columns, create_users_sql)
		ensure_table_schema(conn, "peixes", peixes_columns, create_peixes_sql)
		conn.commit()


def allowed_file(filename: str) -> bool:
	"""Valida se o arquivo tem extensão de imagem permitida."""
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_admin_user(user_id: int) -> bool:
	if not user_id:
		return False

	if user_id in ADMIN_USER_IDS:
		return True

	if not ADMIN_EMAILS:
		return False

	with get_db_connection() as conn:
		user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()

	if not user:
		return False

	return user["email"].strip().lower() in ADMIN_EMAILS


def is_within_delete_window(data_postagem: str) -> bool:
	try:
		post_date = datetime.strptime(data_postagem, "%Y-%m-%d %H:%M:%S")
	except ValueError:
		return False

	deadline = post_date + timedelta(minutes=DELETE_WINDOW_MINUTES)
	return datetime.now() <= deadline


def can_delete_peixe(current_user_id: int, peixe_user_id: int, data_postagem: str) -> bool:
	if is_admin_user(current_user_id):
		return True

	if current_user_id != peixe_user_id:
		return False

	return is_within_delete_window(data_postagem)


def login_required(f):
	@wraps(f)
	def decorated_function(*args, **kwargs):
		if "user_id" not in session:
			return redirect(url_for("login"))
		return f(*args, **kwargs)
	return decorated_function


@app.context_processor
def inject_logged_user():
	"""Disponibiliza nome do usuário logado em todos os templates."""
	return {
		"logged_user_name": session.get("user_nome"),
		"logged_user_id": session.get("user_id"),
	}


@app.route("/")
def boas_vindas():
	if "user_id" in session:
		return redirect(url_for("index"))
	return redirect(url_for("login"))


@app.route("/inicio")
@login_required
def index():
	"""Página inicial com listagem geral, busca por nome e filtro por região."""
	q = request.args.get("q", "").strip()
	regiao = request.args.get("regiao", "").strip()

	query = """
	SELECT
		p.id,
		p.nome_comum,
		p.nome_cientifico,
		p.regiao,
		p.descricao,
		p.foto,
		p.user_id,
		p.data_postagem,
		u.nome AS usuario_nome
	FROM peixes p
	JOIN users u ON u.id = p.user_id
	WHERE 1=1
	"""
	params = []

	if q:
		query += " AND p.nome_comum LIKE ?"
		params.append(f"%{q}%")

	if regiao:
		query += " AND p.regiao = ?"
		params.append(regiao)

	query += " ORDER BY datetime(p.data_postagem) DESC"

	with get_db_connection() as conn:
		peixes_db = conn.execute(query, params).fetchall()
		regioes = conn.execute("SELECT DISTINCT regiao FROM peixes ORDER BY regiao").fetchall()

	current_user_id = session.get("user_id")
	current_user_is_admin = is_admin_user(current_user_id)
	peixes = []

	for peixe in peixes_db:
		peixe_dict = dict(peixe)
		peixe_dict["is_owner"] = peixe_dict["user_id"] == current_user_id
		peixe_dict["can_delete"] = can_delete_peixe(current_user_id, peixe_dict["user_id"], peixe_dict["data_postagem"])
		peixe_dict["delete_window_expired"] = peixe_dict["is_owner"] and not current_user_is_admin and not is_within_delete_window(peixe_dict["data_postagem"])
		peixes.append(peixe_dict)

	return render_template(
		"index.html",
		peixes=peixes,
		q=q,
		regiao_selecionada=regiao,
		regioes=[item["regiao"] for item in regioes],
	)


@app.route("/registrar", methods=["GET", "POST"])
def registrar():
	"""Cadastro de novo usuário com senha criptografada."""
	if request.method == "POST":
		nome = request.form.get("nome", "").strip()
		email = request.form.get("email", "").strip().lower()
		senha = request.form.get("senha", "")

		if not nome or not email or not senha:
			flash("Preencha nome, e-mail e senha.", "danger")
			return redirect(url_for("registrar"))

		senha_hash = generate_password_hash(senha)
		data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

		try:
			with get_db_connection() as conn:
				conn.execute(
					"INSERT INTO users (nome, email, senha, data_criacao) VALUES (?, ?, ?, ?)",
					(nome, email, senha_hash, data_criacao),
				)
				conn.commit()
		except sqlite3.IntegrityError:
			flash("Este e-mail já está cadastrado.", "warning")
			return redirect(url_for("registrar"))

		flash("Conta criada com sucesso. Faça login.", "success")
		return redirect(url_for("login"))

	return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
	"""Autenticação de usuário e criação de sessão."""
	if request.method == "POST":
		email = request.form.get("email", "").strip().lower()
		senha = request.form.get("senha", "")

		with get_db_connection() as conn:
			user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

		if not user or not check_password_hash(user["senha"], senha):
			flash("E-mail ou senha inválidos.", "danger")
			return redirect(url_for("login"))

		session["user_id"] = user["id"]
		session["user_nome"] = user["nome"]
		flash("Login realizado com sucesso!", "success")
		return redirect(url_for("index"))

	return render_template("login.html")


@app.route("/logout")
def logout():
	"""Finaliza a sessão atual."""
	session.clear()
	flash("Você saiu da sua conta.", "info")
	return redirect(url_for("boas_vindas"))


@app.route("/peixes/<int:peixe_id>/deletar", methods=["POST"])
@login_required
def deletar_peixe(peixe_id: int):
	current_user_id = session.get("user_id")

	with get_db_connection() as conn:
		peixe = conn.execute(
			"SELECT id, user_id, foto, data_postagem FROM peixes WHERE id = ?",
			(peixe_id,),
		).fetchone()

		if not peixe:
			flash("Peixe não encontrado.", "warning")
			return redirect(url_for("index"))

		if not can_delete_peixe(current_user_id, peixe["user_id"], peixe["data_postagem"]):
			flash("Você só pode excluir sua foto em até 20 minutos após a postagem. Depois disso, apenas administrador.", "danger")
			return redirect(url_for("index"))

		conn.execute("DELETE FROM peixes WHERE id = ?", (peixe_id,))
		conn.commit()

	foto_path = os.path.join(app.config["UPLOAD_FOLDER"], peixe["foto"])
	if os.path.exists(foto_path):
		os.remove(foto_path)

	flash("Foto removida com sucesso.", "success")
	return redirect(url_for("index"))


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar_peixe():
	"""Cadastro de peixe vinculado ao usuário autenticado."""
	if request.method == "POST":
		nome_comum = request.form.get("nome_comum", "").strip()
		nome_cientifico = request.form.get("nome_cientifico", "").strip()
		regiao = request.form.get("regiao", "").strip()
		descricao = request.form.get("descricao", "").strip()
		arquivo = request.files.get("foto") or request.files.get("imagem") or request.files.get("emagen")

		if not all([nome_comum, nome_cientifico, regiao, descricao]):
			flash("Preencha todos os campos de texto.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not arquivo or arquivo.filename == "":
			flash("Selecione uma imagem para o peixe.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not allowed_file(arquivo.filename):
			flash("Formato de imagem inválido. Use PNG, JPG, JPEG, GIF ou WEBP.", "danger")
			return redirect(url_for("adicionar_peixe"))

		nome_seguro = secure_filename(arquivo.filename)
		nome_arquivo = f"{uuid4().hex}_{nome_seguro}"
		caminho_arquivo = os.path.join(app.config["UPLOAD_FOLDER"], nome_arquivo)
		arquivo.save(caminho_arquivo)

		data_postagem = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

		with get_db_connection() as conn:
			conn.execute(
				"""
				INSERT INTO peixes (nome_comum, nome_cientifico, regiao, descricao, foto, user_id, data_postagem)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				""",
				(
					nome_comum,
					nome_cientifico,
					regiao,
					descricao,
					nome_arquivo,
					session["user_id"],
					data_postagem,
				),
			)
			conn.commit()

		flash("Peixe cadastrado com sucesso!", "success")
		return redirect(url_for("index"))

	return render_template("add_fish.html")


init_db()


if __name__ == "__main__":
	app.run()
