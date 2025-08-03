
import os
import re
import hashlib
import io
import requests
import json
import sqlite3
from flask import Flask, request, render_template, session
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from datetime import datetime

load_dotenv()

OCR_SPACE_API_KEY = "K87180078988957"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1401335008307712110/oSA963JE134fZr89vE0BRFjOH2ruaotjigf1G3AXfFhoU4xu2Zk6HUMpmzmwyD9nGbVP"
UPLOAD_FOLDER = 'uploads'
DATABASE_FILE = 'analises.db'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = os.getenv("FLASK_SECRET_KEY", "chave-secreta-para-hackathon")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash_conteudo TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            erros_detectados TEXT,
            texto_extraido TEXT,
            score_risco INTEGER,
            nivel_risco TEXT
        )
    ''')
    conn.commit()
    conn.close()

def analisar_texto_final(texto_extraido):
    erros_detectados = []
    palavras_para_realcar = set()
    score_risco = 0
    texto_lower = texto_extraido.lower()

    PALAVRAS_INSTITUCIONAIS = ['campus', 'instituto', 'secretaria', 'prefeitura', 'comissao', 'diretoria', 'coordenacao', 'avaliacao', 'servicos', 'companhia', 'programa', 'nacional', 'boletim', 'reitoria', 'grupo', 'trabalho', 'assistencia', 'estudantil']
    nomes_potenciais = re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b", texto_extraido)
    nomes_validos = [nome for nome in nomes_potenciais if not any(palavra in nome.lower() for palavra in PALAVRAS_INSTITUCIONAIS)]
    nomes_contados = {nome: nomes_validos.count(nome) for nome in set(nomes_validos)}
    for nome, contagem in nomes_contados.items():
        if contagem > 1:
            erro = f"🔁 Nome Repetido Suspeito: '{nome}' (aparece {contagem} vezes)"
            erros_detectados.append(erro)
            palavras_para_realcar.add(nome)
            score_risco += 10 * (contagem - 1)

    datas = re.findall(r"\d{2}/\d{2}/\d{4}", texto_extraido)
    for data in datas:
        try:
            d, m, _ = map(int, data.split("/"))
            if d > 31 or m > 12 or d == 0 or m == 0:
                erro = f"⚠️ Data Inválida: '{data}'"
                erros_detectados.append(erro)
                palavras_para_realcar.add(data)
                score_risco += 20
        except: continue

    if not re.search(r"(of[íi]cio|processo|portaria|decreto|contrato)\s+n[ºo]?", texto_lower):
        erros_detectados.append("❌ Estrutura Incompleta: Não foi encontrado um número de documento oficial.")
        score_risco += 30

    palavras_suspeitas = ["dispensa de licitação", "caráter de urgência", "pagamento retroativo", "inexigibilidade de licitação"]
    for palavra in palavras_suspeitas:
        if palavra in texto_lower:
            erro = f"⚠️ Palavra suspeita: '{palavra}'"
            erros_detectados.append(erro)
            palavras_para_realcar.add(palavra)
            score_risco += 40
            
    LIMITE_DISPENSA_SERVICOS = 59906.02
    if "dispensa de licitação" in texto_lower:
        valores_encontrados = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", texto_extraido)
        for valor_str in valores_encontrados:
            valor_float = float(valor_str.replace('.', '').replace(',', '.'))
            if valor_float > LIMITE_DISPENSA_SERVICOS:
                erro = f"ALERTA GRAVE: Valor de R$ {valor_str} em dispensa acima do limite legal."
                erros_detectados.append(erro)
                palavras_para_realcar.add(valor_str)
                score_risco += 100

    status = "SUSPEITO" if erros_detectados else "SEGURO"
    nivel_risco = "Nenhum"
    if score_risco > 0:
        if score_risco <= 39: nivel_risco = "Baixo"
        elif score_risco <= 99: nivel_risco = "Alto"
        else: nivel_risco = "Crítico"

    return {"status": status, "erros": erros_detectados, "score": score_risco, "nivel": nivel_risco, "realce": palavras_para_realcar}

def enviar_alerta_discord(resultado, nome_arquivo):
    if not DISCORD_WEBHOOK_URL or "SEU_ID" in DISCORD_WEBHOOK_URL:
        print("URL do Webhook do Discord não configurada.")
        return

    embed = {
        "title": f"🚨 Alerta: Documento Suspeito Detectado!",
        "color": 15158332,
        "fields": [
            {"name": "Nome do Arquivo", "value": nome_arquivo, "inline": True},
            {"name": "Nível de Risco", "value": resultado['nivel'], "inline": True},
            {"name": "Pontuação de Risco", "value": str(resultado['score']), "inline": True},
            {"name": "Hash do Conteúdo", "value": f"`{resultado['hash']}`"},
            {"name": "Inconsistências Encontradas", "value": "\n".join([f"• {erro}" for erro in resultado['erros']])}
        ],
        "footer": {"text": "Análise concluída pelo Verificador Inteligente."}
    }
    data = {"content": "Um novo documento suspeito requer atenção imediata!", "embeds": [embed]}
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})
        print("Notificação enviada ao Discord com sucesso.")
    except Exception as e:
        print(f"Erro ao enviar notificação para o Discord: {e}")

@app.route('/')
def pagina_inicial():
    return render_template('inicial.html')

@app.route('/verificador', methods=['GET', 'POST'])
def pagina_verificador():
    resultado_analise = None
    erro_upload = None
    if request.method == 'POST':
        if 'file' not in request.files or request.files['file'].filename == '':
            erro_upload = "Nenhum arquivo selecionado."
            return render_template('verificador.html', erro_upload=erro_upload)
        
        file = request.files['file']
        
        if file:
            try:
                file_bytes = file.read()
                
                url = "https://api.ocr.space/parse/image"
                payload = {'language': 'por', 'isOverlayRequired': 'false', 'OCREngine': 2}
                files = {'file': (file.filename, file_bytes, file.content_type)}
                headers = {'apikey': OCR_SPACE_API_KEY}
                response = requests.post(url, headers=headers, data=payload, files=files)
                response.raise_for_status()
                result = response.json()

                if result.get("IsErroredOnProcessing") or not result.get("ParsedResults"):
                    raise ValueError("Erro no OCR ou nenhum texto extraído.")

                texto_extraido = result["ParsedResults"][0]["ParsedText"]
                if not texto_extraido.strip():
                       raise ValueError("Documento vazio ou ilegível.")

                hash_sha256 = hashlib.sha256(texto_extraido.encode('utf-8')).hexdigest()
                
                conn = sqlite3.connect(DATABASE_FILE)
                cursor = conn.cursor()
                cursor.execute("SELECT status, erros_detectados, texto_extraido, score_risco, nivel_risco FROM analises WHERE hash_conteudo = ?", (hash_sha256,))
                analise_existente = cursor.fetchone()
                
                if analise_existente:
                    resultado_analise = {
                        "status": analise_existente[0], "erros": json.loads(analise_existente[1]),
                        "hash": hash_sha256, "texto": analise_existente[2],
                        "score": analise_existente[3], "nivel": analise_existente[4]
                    }
                else:
                    analise = analisar_texto_final(texto_extraido)
                    resultado_analise = {
                        "status": analise['status'], "erros": analise['erros'],
                        "hash": hash_sha256, "texto": texto_extraido,
                        "score": analise['score'], "nivel": analise['nivel']
                    }
                    cursor.execute(
                        "INSERT INTO analises (hash_conteudo, status, erros_detectados, texto_extraido, score_risco, nivel_risco) VALUES (?, ?, ?, ?, ?, ?)",
                        (hash_sha256, resultado_analise['status'], json.dumps(resultado_analise['erros']), texto_extraido, resultado_analise['score'], resultado_analise['nivel'])
                    )
                    conn.commit()
                
                conn.close()

                texto_realcado = texto_extraido
                palavras_para_realcar = analisar_texto_final(texto_extraido)['realce']
                for palavra in palavras_para_realcar:
                    texto_realcado = re.sub(f"({re.escape(palavra)})", r"<mark>\1</mark>", texto_realcado, flags=re.IGNORECASE)
                resultado_analise['texto_realcado'] = texto_realcado

                session['ultimo_resultado'] = resultado_analise

                if resultado_analise['status'] == 'SUSPEITO':
                    enviar_alerta_discord(resultado_analise, file.filename)

            except Exception as e:
                resultado_analise = {"status": "ERRO", "erros": [f"Não foi possível processar o arquivo: {e}"]}
            
    return render_template('verificador.html', resultado=resultado_analise, erro_upload=erro_upload)

@app.route('/relatorio')
def pagina_relatorio():
    resultado = session.get('ultimo_resultado', None)
    if not resultado:
        return "Nenhum resultado de análise encontrado para gerar o relatório.", 404
    
    return render_template(
        'relatorio.html',
        resultado=resultado,
        data_analise=datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    )

@app.route('/transparencia')
def pagina_transparencia():
    return render_template('transparencia.html')

@app.route('/login')
def pagina_login():
    return render_template('login.html')

@app.route('/cadastro')
def pagina_cadastro():
    return render_template('cadastro.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
