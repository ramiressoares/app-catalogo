import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, List, Optional, Sequence

import cloudinary
import cloudinary.uploader
import psycopg2
from psycopg2 import extras as psycopg2_extras
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


LEGACY_UPLOADS_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "static", "uploads")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
	raise RuntimeError("A variavel de ambiente DATABASE_URL e obrigatoria no Render.")

if DATABASE_URL.startswith("postgres://"):
	DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Extensoes de imagem permitidas para upload
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
DELETE_WINDOW_MINUTES = 20
ADMIN_USER_IDS = {1}
ADMIN_EMAILS = {email.strip().lower() for email in os.getenv("ADMIN_EMAILS", "").split(",") if email.strip()}
DB_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (psycopg2.IntegrityError,)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.secret_key = "catalogo-peixes-secret"

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")


class DBConnection:
	"""Wrapper para padronizar placeholders SQL no psycopg2."""

	def __init__(self, conn: Any):
		self._conn = conn

	def _normalize_query(self, query: str) -> str:
		return query.replace("?", "%s")

	def execute(self, query: str, params: Optional[Sequence[Any]] = None):
		cursor = self._conn.cursor()
		cursor.execute(self._normalize_query(query), tuple(params or ()))
		return cursor

	def commit(self) -> None:
		self._conn.commit()

	def rollback(self) -> None:
		self._conn.rollback()

	def close(self) -> None:
		self._conn.close()

	def __enter__(self) -> "DBConnection":
		return self

	def __exit__(self, exc_type, exc, tb) -> bool:
		if exc:
			self.rollback()
		self.close()
		return False


def get_db_connection() -> DBConnection:
	"""Conecta ao PostgreSQL do Render via DATABASE_URL."""
	conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2_extras.DictCursor)
	return DBConnection(conn)


def init_db() -> None:
	"""Cria as tabelas no PostgreSQL automaticamente ao iniciar o app."""
	with get_db_connection() as conn:
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS usuarios (
				id SERIAL PRIMARY KEY,
				nome TEXT,
				email TEXT,
				senha TEXT
			)
			"""
		)

		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS peixes (
				id SERIAL PRIMARY KEY,
				nome TEXT,
				especie TEXT,
				regiao TEXT,
				imagem_url TEXT,
				usuario_id INTEGER,
				data_postagem TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			)
			"""
		)

		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS comentarios (
				id SERIAL PRIMARY KEY,
				peixe_id INTEGER,
				usuario_id INTEGER,
				comentario TEXT,
				data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			)
			"""
		)

		conn.commit()


def get_missing_cloudinary_vars() -> List[str]:
	missing = []
	if not CLOUDINARY_CLOUD_NAME:
		missing.append("CLOUDINARY_CLOUD_NAME")
	if not CLOUDINARY_API_KEY:
		missing.append("CLOUDINARY_API_KEY")
	if not CLOUDINARY_API_SECRET:
		missing.append("CLOUDINARY_API_SECRET")
	return missing


cloudinary.config(
	cloud_name=CLOUDINARY_CLOUD_NAME,
	api_key=CLOUDINARY_API_KEY,
	api_secret=CLOUDINARY_API_SECRET,
	secure=True,
)

missing_cloudinary_vars = get_missing_cloudinary_vars()
if missing_cloudinary_vars:
	app.logger.warning(
		"Cloudinary desconfigurado. Variaveis ausentes: %s",
		", ".join(missing_cloudinary_vars),
	)


def migrate_legacy_images_to_cloudinary() -> None:
	"""Migra registros antigos (nome de arquivo local) para URL Cloudinary."""
	missing_vars = get_missing_cloudinary_vars()
	if missing_vars:
		app.logger.warning(
			"Migracao legada ignorada: variaveis Cloudinary ausentes (%s)",
			", ".join(missing_vars),
		)
		return

	with get_db_connection() as conn:
		legacy_rows = conn.execute(
			"""
			SELECT id, imagem_url
			FROM peixes
			WHERE TRIM(imagem_url) != ''
			AND imagem_url NOT LIKE 'http://%'
			AND imagem_url NOT LIKE 'https://%'
			"""
		).fetchall()

		if not legacy_rows:
			return

		migrated = 0
		for row in legacy_rows:
			peixe_id = row["id"]
			legacy_value = (row["imagem_url"] or "").strip()

			if not legacy_value:
				continue

			file_name = os.path.basename(legacy_value)
			local_path = os.path.join(LEGACY_UPLOADS_DIR, file_name)

			if not os.path.isfile(local_path):
				app.logger.warning(
					"Migracao legada: arquivo nao encontrado para peixe %s (%s)",
					peixe_id,
					local_path,
				)
				continue

			try:
				with open(local_path, "rb") as image_file:
					result = cloudinary.uploader.upload(image_file)
			except Exception as exc:
				app.logger.exception(
					"Migracao legada: erro no upload Cloudinary para peixe %s (%s): %s",
					peixe_id,
					local_path,
					exc,
				)
				continue

			secure_url = result.get("secure_url")
			if not secure_url:
				app.logger.error(
					"Migracao legada: Cloudinary sem secure_url para peixe %s. Resposta: %s",
					peixe_id,
					result,
				)
				continue

			conn.execute("UPDATE peixes SET imagem_url = ? WHERE id = ?", (secure_url, peixe_id))
			migrated += 1

		conn.commit()

	if migrated:
		app.logger.info("Migracao legada concluida: %s imagem(ns) atualizada(s) para Cloudinary.", migrated)


def allowed_file(filename: str) -> bool:
	"""Valida se o arquivo tem extensao de imagem permitida."""
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def resolve_image_src(imagem_url: str) -> str:
	"""Normaliza URL da imagem para exibicao no site."""
	if not imagem_url:
		return ""

	value = imagem_url.strip()
	if value.startswith("http://") or value.startswith("https://"):
		return value
	if value.startswith("/static/"):
		return value
	if value.startswith("static/"):
		return f"/{value}"
	if value.startswith("uploads/"):
		return url_for("static", filename=value)

	# Compatibilidade com registros antigos que guardavam apenas nome de arquivo local.
	return url_for("static", filename=f"uploads/{value}")


def is_admin_user(user_id: int) -> bool:
	if not user_id:
		return False

	if user_id in ADMIN_USER_IDS:
		return True

	if not ADMIN_EMAILS:
		return False

	with get_db_connection() as conn:
		user = conn.execute("SELECT email FROM usuarios WHERE id = ?", (user_id,)).fetchone()

	if not user:
		return False

	return user["email"].strip().lower() in ADMIN_EMAILS


def is_within_delete_window(data_postagem: str) -> bool:
	if isinstance(data_postagem, datetime):
		post_date = data_postagem
	else:
		try:
			post_date = datetime.fromisoformat(str(data_postagem).replace("Z", "+00:00")).replace(tzinfo=None)
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
	"""Disponibiliza nome do usuario logado em todos os templates."""
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
	"""Pagina inicial com listagem geral, busca por nome e filtro por regiao."""
	q = request.args.get("q", "").strip()
	regiao = request.args.get("regiao", "").strip()

	query = """
	SELECT
		p.id,
		p.nome,
		p.especie,
		p.regiao,
		p.imagem_url,
		p.usuario_id,
		p.data_postagem,
		u.nome AS usuario_nome
	FROM peixes p
	JOIN usuarios u ON u.id = p.usuario_id
	WHERE 1=1
	"""
	params = []

	if q:
		query += " AND p.nome LIKE ?"
		params.append(f"%{q}%")

	if regiao:
		query += " AND p.regiao = ?"
		params.append(regiao)

	query += " ORDER BY p.data_postagem DESC"

	with get_db_connection() as conn:
		peixes_db = conn.execute(query, params).fetchall()
		regioes = conn.execute("SELECT DISTINCT regiao FROM peixes ORDER BY regiao").fetchall()
		total_peixes = conn.execute("SELECT COUNT(*) FROM peixes").fetchone()[0]
		total_pescadores = conn.execute("SELECT COUNT(DISTINCT usuario_id) FROM peixes").fetchone()[0]

	current_user_id = session.get("user_id")
	current_user_is_admin = is_admin_user(current_user_id)
	peixes = []

	for peixe in peixes_db:
		peixe_dict = dict(peixe)
		peixe_dict["imagem_src"] = resolve_image_src(peixe_dict.get("imagem_url"))
		peixe_dict["nome_comum"] = peixe_dict.get("nome")
		peixe_dict["nome_cientifico"] = peixe_dict.get("especie")
		peixe_dict["descricao"] = ""
		peixe_dict["is_owner"] = peixe_dict["usuario_id"] == current_user_id
		peixe_dict["can_delete"] = can_delete_peixe(current_user_id, peixe_dict["usuario_id"], peixe_dict["data_postagem"])
		peixe_dict["delete_window_expired"] = peixe_dict["is_owner"] and not current_user_is_admin and not is_within_delete_window(peixe_dict["data_postagem"])
		peixes.append(peixe_dict)

	return render_template(
		"index.html",
		peixes=peixes,
		q=q,
		regiao_selecionada=regiao,
		regioes=[item["regiao"] for item in regioes],
		total_peixes=total_peixes,
		total_pescadores=total_pescadores,
	)


@app.route("/registrar", methods=["GET", "POST"])
def registrar():
	"""Cadastro de novo usuario com senha criptografada."""
	if request.method == "POST":
		nome = request.form.get("nome", "").strip()
		email = request.form.get("email", "").strip().lower()
		senha = request.form.get("senha", "")

		if not nome or not email or not senha:
			flash("Preencha nome, e-mail e senha.", "danger")
			return redirect(url_for("registrar"))

		senha_hash = generate_password_hash(senha)
		with get_db_connection() as conn:
			existing_user = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
			if existing_user:
				flash("Este e-mail ja esta cadastrado.", "warning")
				return redirect(url_for("registrar"))

			conn.execute(
				"INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
				(nome, email, senha_hash),
			)
			conn.commit()

		flash("Conta criada com sucesso. Faca login.", "success")
		return redirect(url_for("login"))

	return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
	"""Autenticacao de usuario e criacao de sessao."""
	if request.method == "POST":
		email = request.form.get("email", "").strip().lower()
		senha = request.form.get("senha", "")

		with get_db_connection() as conn:
			user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

		if not user or not check_password_hash(user["senha"], senha):
			flash("E-mail ou senha invalidos.", "danger")
			return redirect(url_for("login"))

		session["user_id"] = user["id"]
		session["user_nome"] = user["nome"]
		flash("Login realizado com sucesso!", "success")
		return redirect(url_for("index"))

	return render_template("login.html")


@app.route("/logout")
def logout():
	"""Finaliza a sessao atual."""
	session.clear()
	flash("Voce saiu da sua conta.", "info")
	return redirect(url_for("boas_vindas"))


@app.route("/peixes/<int:peixe_id>/deletar", methods=["POST"])
@login_required
def deletar_peixe(peixe_id: int):
	current_user_id = session.get("user_id")

	with get_db_connection() as conn:
		peixe = conn.execute(
			"SELECT id, usuario_id, imagem_url, data_postagem FROM peixes WHERE id = ?",
			(peixe_id,),
		).fetchone()

		if not peixe:
			flash("Peixe nao encontrado.", "warning")
			return redirect(url_for("index"))

		if not can_delete_peixe(current_user_id, peixe["usuario_id"], peixe["data_postagem"]):
			flash("Voce so pode excluir sua foto em ate 20 minutos apos a postagem. Depois disso, apenas administrador.", "danger")
			return redirect(url_for("index"))

		conn.execute("DELETE FROM peixes WHERE id = ?", (peixe_id,))
		conn.commit()

	flash("Foto removida com sucesso.", "success")
	return redirect(url_for("index"))


@app.route("/peixes/<int:peixe_id>/editar-nome-cientifico", methods=["POST"])
@login_required
def editar_nome_cientifico(peixe_id: int):
	current_user_id = session.get("user_id")
	novo_nome_cientifico = request.form.get("nome_cientifico", "").strip()

	if not novo_nome_cientifico:
		flash("Informe um nome cientifico valido.", "danger")
		return redirect(url_for("index"))

	with get_db_connection() as conn:
		peixe = conn.execute(
			"SELECT id, usuario_id FROM peixes WHERE id = ?",
			(peixe_id,),
		).fetchone()

		if not peixe:
			flash("Peixe nao encontrado.", "warning")
			return redirect(url_for("index"))

		if peixe["usuario_id"] != current_user_id:
			flash("Apenas o dono da foto pode editar o nome cientifico.", "danger")
			return redirect(url_for("index"))

		conn.execute(
			"UPDATE peixes SET especie = ? WHERE id = ?",
			(novo_nome_cientifico, peixe_id),
		)
		conn.commit()

	flash("Nome cientifico atualizado com sucesso.", "success")
	return redirect(url_for("index"))


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar_peixe():
	"""Cadastro de peixe vinculado ao usuário autenticado."""
	if request.method == "POST":
		nome_comum = request.form.get("nome_comum", "").strip()
		nome_cientifico = request.form.get("nome_cientifico", "").strip()
		regiao = request.form.get("regiao", "").strip()

		file = request.files.get("foto")

		if not all([nome_comum, nome_cientifico, regiao]):
			flash("Preencha todos os campos de texto.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not file or file.filename == "":
			flash("Selecione uma imagem para o peixe.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not allowed_file(file.filename):
			flash("Formato de imagem invalido. Use PNG, JPG, JPEG, GIF ou WEBP.", "danger")
			return redirect(url_for("adicionar_peixe"))

		missing_vars = get_missing_cloudinary_vars()
		if missing_vars:
			app.logger.error("Upload bloqueado: Cloudinary sem configuracao. Variaveis ausentes: %s", ", ".join(missing_vars))
			flash("Configuracao de upload ausente no servidor (Cloudinary).", "danger")
			return redirect(url_for("adicionar_peixe"))

		try:
			result = cloudinary.uploader.upload(file.stream)
		except Exception as exc:
			app.logger.exception("Erro ao enviar imagem para o Cloudinary: %s", exc)
			flash(f"Erro Cloudinary: {exc}", "danger")
			return redirect(url_for("adicionar_peixe"))

		if "secure_url" not in result:
			app.logger.error("Resposta do Cloudinary sem secure_url: %s", result)
			flash("Cloudinary nao retornou URL segura da imagem.", "danger")
			return redirect(url_for("adicionar_peixe"))

		image_url = result["secure_url"]
		if not image_url:
			flash("Cloudinary nao retornou URL da imagem.", "danger")
			return redirect(url_for("adicionar_peixe"))

		with get_db_connection() as conn:
			conn.execute(
				"""
				INSERT INTO peixes (nome, especie, regiao, imagem_url, usuario_id)
				VALUES (?, ?, ?, ?, ?)
				""",
				(
					nome_comum,
					nome_cientifico,
					regiao,
					image_url,
					session["user_id"],
				),
			)
			conn.commit()

		flash("Peixe cadastrado com sucesso!", "success")
		return redirect(url_for("index"))

	return render_template("add_fish.html")


init_db()

if os.getenv("AUTO_MIGRATE_LEGACY_IMAGES", "0") == "1":
	migrate_legacy_images_to_cloudinary()


if __name__ == "__main__":
	app.run()
