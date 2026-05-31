import os
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, List, Optional, Sequence

import cloudinary
import cloudinary.uploader
import psycopg2
import psycopg2.extras
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


LEGACY_UPLOADS_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "static", "uploads")
logger = logging.getLogger(__name__)

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
	"""Conecta ao PostgreSQL via DATABASE_URL com timeout e DictCursor."""
	database_url = os.getenv("DATABASE_URL")

	if not database_url:
		raise Exception("DATABASE_URL nao esta configurada")

	database_url = database_url.strip()

	# Compatibilidade com URLs legadas do Render.
	if database_url.startswith("postgres://"):
		database_url = database_url.replace("postgres://", "postgresql://", 1)

	try:
		conn = psycopg2.connect(
			database_url,
			connect_timeout=10,
			cursor_factory=psycopg2.extras.DictCursor,
		)
		return DBConnection(conn)
	except Exception as e:
		logger.error("Erro ao conectar no banco: %s", e)
		raise


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
				parent_id INTEGER,
				comentario TEXT,
				data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			)
			"""
		)

		# Compatibilidade com bases antigas sem suporte a resposta de comentarios.
		conn.execute("ALTER TABLE comentarios ADD COLUMN IF NOT EXISTS parent_id INTEGER")

		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS curtidas (
				peixe_id INTEGER NOT NULL,
				usuario_id INTEGER NOT NULL,
				PRIMARY KEY (peixe_id, usuario_id)
			)
			"""
		)

		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS comentario_curtidas (
				comentario_id INTEGER NOT NULL,
				usuario_id INTEGER NOT NULL,
				PRIMARY KEY (comentario_id, usuario_id)
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


def format_data_postagem(data_postagem: Any) -> str:
	"""Formata data como d/m/aaaa h: hh:mm para exibicao no template."""
	if isinstance(data_postagem, datetime):
		post_date = data_postagem
	else:
		try:
			post_date = datetime.fromisoformat(str(data_postagem).replace("Z", "+00:00")).replace(tzinfo=None)
		except ValueError:
			return str(data_postagem)

	return f"{post_date.day}/{post_date.month}/{post_date.year} h: {post_date:%H:%M}"


def format_data_comentario(data_postagem: Any) -> str:
	"""Formata data de comentario em um formato mais compacto para o feed."""
	if isinstance(data_postagem, datetime):
		post_date = data_postagem
	else:
		try:
			post_date = datetime.fromisoformat(str(data_postagem).replace("Z", "+00:00")).replace(tzinfo=None)
		except ValueError:
			return str(data_postagem)

	return f"{post_date.day:02d}/{post_date.month:02d} {post_date:%H:%M}"


def build_comment_node(comment_row: Any, liked_by_user: set[int]) -> dict[str, Any]:
	usuario_nome = (comment_row["usuario_nome"] or "Usuario").strip() if comment_row["usuario_nome"] else "Usuario"
	avatar = usuario_nome[0].upper() if usuario_nome else "U"
	return {
		"id": comment_row["id"],
		"parent_id": comment_row["parent_id"],
		"usuario_nome": usuario_nome,
		"avatar": avatar,
		"comentario": comment_row["comentario"],
		"data": format_data_comentario(comment_row["data"]),
		"curtidas": comment_row["likes_total"] or 0,
		"curtido": comment_row["id"] in liked_by_user,
		"respostas": [],
	}


def load_comments_by_peixe(
	conn: DBConnection,
	peixe_ids: list[int],
	current_user_id: Optional[int],
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, int]]:
	if not peixe_ids:
		return {}, {}

	comments_rows = conn.execute(
		"""
		SELECT
			c.id,
			c.peixe_id,
			c.parent_id,
			c.comentario,
			c.data,
			u.nome AS usuario_nome,
			COUNT(cc.usuario_id)::INTEGER AS likes_total
		FROM comentarios c
		JOIN usuarios u ON u.id = c.usuario_id
		LEFT JOIN comentario_curtidas cc ON cc.comentario_id = c.id
		WHERE c.peixe_id = ANY(%s)
		GROUP BY c.id, c.peixe_id, c.parent_id, c.comentario, c.data, u.nome
		ORDER BY c.data DESC
		""",
		(peixe_ids,),
	).fetchall()

	liked_by_user: set[int] = set()
	if current_user_id:
		liked_rows = conn.execute(
			"""
			SELECT comentario_id
			FROM comentario_curtidas
			WHERE usuario_id = ?
			""",
			(current_user_id,),
		).fetchall()
		liked_by_user = {row["comentario_id"] for row in liked_rows}

	by_peixe: dict[int, list[dict[str, Any]]] = {}
	totals: dict[int, int] = {}
	nodes_by_id: dict[int, dict[str, Any]] = {}

	for row in comments_rows:
		node = build_comment_node(row, liked_by_user)
		nodes_by_id[node["id"]] = node
		peixe_id = row["peixe_id"]
		totals[peixe_id] = totals.get(peixe_id, 0) + 1

	for row in comments_rows:
		node = nodes_by_id[row["id"]]
		parent_id = row["parent_id"]
		peixe_id = row["peixe_id"]

		if parent_id and parent_id in nodes_by_id:
			nodes_by_id[parent_id]["respostas"].append(node)
			continue

		if peixe_id not in by_peixe:
			by_peixe[peixe_id] = []
		by_peixe[peixe_id].append(node)

	return by_peixe, totals


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
			flash("Faça login para publicar e acompanhar os registros.", "warning")
			return redirect(url_for("login", next=request.url))
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

	current_user_id = session.get("user_id")
	current_user_is_admin = is_admin_user(current_user_id)

	with get_db_connection() as conn:
		peixes_db = conn.execute(query, params).fetchall()
		regioes = conn.execute("SELECT DISTINCT regiao FROM peixes ORDER BY regiao").fetchall()
		total_peixes = conn.execute("SELECT COUNT(*) FROM peixes").fetchone()[0]
		total_pescadores = conn.execute("SELECT COUNT(DISTINCT usuario_id) FROM peixes").fetchone()[0]
		peixe_ids = [row["id"] for row in peixes_db]

		# Busca contagens de curtidas e quais o usuario logado curtiu
		try:
			curtidas_count = {
				row["peixe_id"]: row["total"]
				for row in conn.execute("SELECT peixe_id, COUNT(*) AS total FROM curtidas GROUP BY peixe_id").fetchall()
			}
			curtidas_usuario: set = set()
			if current_user_id:
				curtidas_usuario = {
					row["peixe_id"]
					for row in conn.execute(
						"SELECT peixe_id FROM curtidas WHERE usuario_id = ?", (current_user_id,)
					).fetchall()
				}
		except Exception:
			curtidas_count = {}
			curtidas_usuario = set()

		try:
			comentarios_por_peixe, comentarios_count = load_comments_by_peixe(conn, peixe_ids, current_user_id)
		except Exception:
			comentarios_por_peixe = {}
			comentarios_count = {}

	peixes = []

	for peixe in peixes_db:
		peixe_dict = dict(peixe)
		data_postagem_raw = peixe_dict.get("data_postagem")
		peixe_dict["imagem_src"] = resolve_image_src(peixe_dict.get("imagem_url"))
		peixe_dict["nome_comum"] = peixe_dict.get("nome")
		peixe_dict["nome_cientifico"] = peixe_dict.get("especie")
		peixe_dict["descricao"] = ""
		peixe_dict["is_owner"] = peixe_dict["usuario_id"] == current_user_id
		peixe_dict["can_delete"] = can_delete_peixe(current_user_id, peixe_dict["usuario_id"], data_postagem_raw)
		peixe_dict["delete_window_expired"] = peixe_dict["is_owner"] and not current_user_is_admin and not is_within_delete_window(data_postagem_raw)
		peixe_dict["data_postagem"] = format_data_postagem(data_postagem_raw)
		peixe_dict["curtidas"] = curtidas_count.get(peixe_dict["id"], 0)
		peixe_dict["curtido"] = peixe_dict["id"] in curtidas_usuario
		peixe_dict["comentarios_total"] = comentarios_count.get(peixe_dict["id"], 0)
		peixe_dict["comentarios_preview"] = comentarios_por_peixe.get(peixe_dict["id"], [])
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
			flash("Preencha nome, e-mail e senha para concluir seu cadastro.", "danger")
			return redirect(url_for("registrar"))

		senha_hash = generate_password_hash(senha)
		with get_db_connection() as conn:
			existing_user = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
			if existing_user:
				flash("Ja existe uma conta vinculada a este e-mail.", "warning")
				return redirect(url_for("registrar"))

			conn.execute(
				"INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
				(nome, email, senha_hash),
			)
			conn.commit()

		flash("Cadastro concluido com sucesso. Entre para iniciar sua participacao.", "success")
		return redirect(url_for("login"))

	return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
	"""Autenticacao de usuario e criacao de sessao."""
	if request.method == "POST":
		email = request.form.get("email", "").strip().lower()
		senha = request.form.get("senha", "")
		next_url = request.form.get("next") or request.args.get("next")

		with get_db_connection() as conn:
			user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

		if not user or not check_password_hash(user["senha"], senha):
			flash("Nao foi possivel validar seu acesso. Revise e-mail e senha.", "danger")
			return redirect(url_for("login"))

		session["user_id"] = user["id"]
		session["user_nome"] = user["nome"]
		flash("Acesso realizado com sucesso.", "success")
		return redirect(next_url or url_for("index"))

	with get_db_connection() as conn:
		total_usuarios = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
		total_especies = conn.execute("SELECT COUNT(*) FROM peixes").fetchone()[0]
		total_regioes = conn.execute(
			"""
			SELECT COUNT(DISTINCT regiao)
			FROM peixes
			WHERE TRIM(COALESCE(regiao, '')) <> ''
			"""
		).fetchone()[0]

	return render_template(
		"login.html",
		login_stats={
			"collaborators": total_usuarios,
			"species": total_especies,
			"regions": total_regioes,
		},
	)


@app.route("/logout")
def logout():
	"""Finaliza a sessao atual."""
	session.clear()
	flash("Sua sessao foi encerrada com seguranca.", "info")
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
			flash("O registro solicitado nao foi localizado.", "warning")
			return redirect(url_for("index"))

		if not can_delete_peixe(current_user_id, peixe["usuario_id"], peixe["data_postagem"]):
			flash("A remocao pelo autor fica disponivel por ate 20 minutos apos a publicacao. Depois disso, a exclusao fica restrita a administracao.", "danger")
			return redirect(url_for("index"))

		conn.execute("DELETE FROM peixes WHERE id = ?", (peixe_id,))
		conn.commit()

	flash("Registro removido do catalogo com sucesso.", "success")
	return redirect(url_for("index"))


@app.route("/peixes/<int:peixe_id>/editar-nome-cientifico", methods=["POST"])
@login_required
def editar_nome_cientifico(peixe_id: int):
	current_user_id = session.get("user_id")
	novo_nome_cientifico = request.form.get("nome_cientifico", "").strip()

	if not novo_nome_cientifico:
		flash("Informe um nome cientifico valido para atualizar o registro.", "danger")
		return redirect(url_for("index"))

	with get_db_connection() as conn:
		peixe = conn.execute(
			"SELECT id, usuario_id FROM peixes WHERE id = ?",
			(peixe_id,),
		).fetchone()

		if not peixe:
			flash("O registro solicitado nao foi localizado.", "warning")
			return redirect(url_for("index"))

		if peixe["usuario_id"] != current_user_id:
			flash("Somente o autor do registro pode atualizar o nome cientifico.", "danger")
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
			flash("Preencha os campos principais do registro antes de publicar.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not file or file.filename == "":
			flash("Selecione uma imagem para compor o registro.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if not allowed_file(file.filename):
			flash("Formato de imagem nao suportado. Utilize PNG, JPG, JPEG, GIF ou WEBP.", "danger")
			return redirect(url_for("adicionar_peixe"))

		missing_vars = get_missing_cloudinary_vars()
		if missing_vars:
			app.logger.error("Upload bloqueado: Cloudinary sem configuracao. Variaveis ausentes: %s", ", ".join(missing_vars))
			flash("O servico de envio de imagens nao esta disponivel no momento.", "danger")
			return redirect(url_for("adicionar_peixe"))

		try:
			result = cloudinary.uploader.upload(file.stream)
		except Exception as exc:
			app.logger.exception("Erro ao enviar imagem para o Cloudinary: %s", exc)
			flash("Nao foi possivel enviar a imagem agora. Tente novamente em instantes.", "danger")
			return redirect(url_for("adicionar_peixe"))

		if "secure_url" not in result:
			app.logger.error("Resposta do Cloudinary sem secure_url: %s", result)
			flash("A imagem foi recebida, mas o servidor nao retornou um endereco valido para publicacao.", "danger")
			return redirect(url_for("adicionar_peixe"))

		image_url = result["secure_url"]
		if not image_url:
			flash("Nao foi possivel concluir o vinculo da imagem ao registro.", "danger")
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

		flash("Registro publicado com sucesso no catalogo.", "success")
		return redirect(url_for("index"))

	return render_template("add_fish.html")


@app.route("/peixes/<int:peixe_id>/curtir", methods=["POST"])
@login_required
def curtir_peixe(peixe_id: int):
	"""Alterna curtida do usuario autenticado em um peixe. Retorna JSON."""
	current_user_id = session.get("user_id")

	with get_db_connection() as conn:
		peixe = conn.execute("SELECT id FROM peixes WHERE id = ?", (peixe_id,)).fetchone()
		if not peixe:
			return jsonify({"error": "Registro nao encontrado."}), 404

		ja_curtiu = conn.execute(
			"SELECT 1 FROM curtidas WHERE peixe_id = ? AND usuario_id = ?",
			(peixe_id, current_user_id),
		).fetchone()

		if ja_curtiu:
			conn.execute(
				"DELETE FROM curtidas WHERE peixe_id = ? AND usuario_id = ?",
				(peixe_id, current_user_id),
			)
			curtido = False
		else:
			conn.execute(
				"INSERT INTO curtidas (peixe_id, usuario_id) VALUES (?, ?)",
				(peixe_id, current_user_id),
			)
			curtido = True

		conn.commit()
		total = conn.execute(
			"SELECT COUNT(*) FROM curtidas WHERE peixe_id = ?", (peixe_id,)
		).fetchone()[0]

	return jsonify({"curtido": curtido, "total": total})


@app.route("/peixes/<int:peixe_id>/comentar", methods=["POST"])
@login_required
def comentar_peixe(peixe_id: int):
	"""Cria um comentario em um peixe e retorna JSON em chamadas assicronas."""
	current_user_id = session.get("user_id")
	comentario = request.form.get("comentario", "").strip()
	parent_id_raw = request.form.get("parent_id", "").strip()
	parent_id: Optional[int] = None
	if parent_id_raw:
		try:
			parent_id = int(parent_id_raw)
		except ValueError:
			parent_id = None

	if not comentario:
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return jsonify({"error": "Escreva uma contribuicao antes de publicar."}), 400
		flash("Escreva uma contribuicao antes de publicar.", "warning")
		return redirect(url_for("index"))

	if len(comentario) > 300:
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return jsonify({"error": "Sua contribuicao excede o limite de 300 caracteres."}), 400
		flash("Sua contribuicao excede o limite de 300 caracteres.", "warning")
		return redirect(url_for("index"))

	with get_db_connection() as conn:
		peixe = conn.execute("SELECT id FROM peixes WHERE id = ?", (peixe_id,)).fetchone()
		if not peixe:
			if request.headers.get("X-Requested-With") == "XMLHttpRequest":
				return jsonify({"error": "Registro nao encontrado."}), 404
			flash("O registro informado nao foi localizado.", "danger")
			return redirect(url_for("index"))

		comment_row = conn.execute(
			"""
			INSERT INTO comentarios (peixe_id, usuario_id, parent_id, comentario)
			VALUES (?, ?, ?, ?)
			RETURNING id, parent_id, comentario, data
			""",
			(peixe_id, current_user_id, parent_id, comentario),
		).fetchone()

		total = conn.execute(
			"SELECT COUNT(*) FROM comentarios WHERE peixe_id = ?",
			(peixe_id,),
		).fetchone()[0]
		conn.commit()

	if request.headers.get("X-Requested-With") == "XMLHttpRequest":
		return jsonify(
			{
				"ok": True,
				"total": total,
				"comentario": {
					"id": comment_row["id"],
					"parent_id": comment_row["parent_id"],
					"usuario_nome": session.get("user_nome", "Voce"),
					"avatar": (session.get("user_nome", "V") or "V")[0].upper(),
					"texto": comment_row["comentario"],
					"data": format_data_comentario(comment_row["data"]),
					"curtidas": 0,
					"curtido": False,
				},
			}
		)

	flash("Contribuicao publicada com sucesso.", "success")
	return redirect(url_for("index"))


@app.route("/comentarios/<int:comentario_id>/curtir", methods=["POST"])
@login_required
def curtir_comentario(comentario_id: int):
	"""Alterna curtida em um comentario e retorna o total atualizado."""
	current_user_id = session.get("user_id")

	with get_db_connection() as conn:
		comentario = conn.execute(
			"SELECT id FROM comentarios WHERE id = ?",
			(comentario_id,),
		).fetchone()
		if not comentario:
			return jsonify({"error": "Contribuicao nao encontrada."}), 404

		ja_curtiu = conn.execute(
			"SELECT 1 FROM comentario_curtidas WHERE comentario_id = ? AND usuario_id = ?",
			(comentario_id, current_user_id),
		).fetchone()

		if ja_curtiu:
			conn.execute(
				"DELETE FROM comentario_curtidas WHERE comentario_id = ? AND usuario_id = ?",
				(comentario_id, current_user_id),
			)
			curtido = False
		else:
			conn.execute(
				"INSERT INTO comentario_curtidas (comentario_id, usuario_id) VALUES (?, ?)",
				(comentario_id, current_user_id),
			)
			curtido = True

		conn.commit()
		total = conn.execute(
			"SELECT COUNT(*) FROM comentario_curtidas WHERE comentario_id = ?",
			(comentario_id,),
		).fetchone()[0]

	return jsonify({"ok": True, "curtido": curtido, "total": total})


init_db()

if __name__ == "__main__":
	app.run()
