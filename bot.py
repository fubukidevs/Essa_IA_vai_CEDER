import os
import logging
import asyncio
import random
import time
import json
import threading
import requests
from datetime import datetime, timedelta, date
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from openai import OpenAI
from flask import Flask, render_template_string
import weakref
from concurrent.futures import ThreadPoolExecutor

# NOVO: Import do sistema de pagamento
from pagamento import detectar_pacote_escolhido, criar_pix_pagamento, formatar_resposta_pix, iniciar_servidor_webhook, definir_callback_pagamento, LINKS_ACESSO
from utmify_tracker import enviar_pix_gerado, enviar_pix_pago

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# OpenAI API configuration
OPENAI_API_KEY = "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"
client = OpenAI(api_key=OPENAI_API_KEY)

# Telegram bot token - substitua pelo seu token do BotFather
TELEGRAM_TOKEN = "8150357292:AAEKY3esw31Ov_7xd8DIg81VNzApfyobp1c"

# Caminho do arquivo de áudio - SUBSTITUA PELO SEU CAMINHO
AUDIO_FILE_PATH = "audios/banho.mp3"  # Modifique este caminho

# Caminho da foto inicial - SUBSTITUA PELO SEU CAMINHO
INITIAL_PHOTO_PATH = "videos/toalha.mp4"  # Modifique este caminho

# Caminho da tabela de preços - SUBSTITUA PELO SEU CAMINHO
PRICE_TABLE_PATH = "img/tabela.png"  # Modifique este caminho

# Caminho do vídeo de prévia - SUBSTITUA PELO SEU CAMINHO
PREVIEW_VIDEO_PATH = "videos/previa.mp4"  # Modifique este caminho

# Caminho do áudio do comprovante - SUBSTITUA PELO SEU CAMINHO  
COMPROVANTE_AUDIO_PATH = "audios/comprovante.mp3"  # Modifique este caminho

# Caminho do áudio explicando conteúdos - SUBSTITUA PELO SEU CAMINHO
EXPLICACAO_AUDIO_PATH = "audios/explicacao.mp3"  # Modifique este caminho

# === OTIMIZAÇÕES DE PERFORMANCE ===
# Pool de threads para operações I/O
thread_pool = ThreadPoolExecutor(max_workers=4)

# Semáforo para controlar concorrência de requests à OpenAI
openai_semaphore = asyncio.Semaphore(10)  # Máximo 10 requests simultâneos

# Controle de rate limiting
last_save_metrics = 0

SAVE_INTERVAL = 30  # Salva métricas a cada 30 segundos no máximo

# === SISTEMA DE MÉTRICAS DASHBOARD OTIMIZADO ===
METRICS_FILE = "bot_metrics.json"

# Estrutura para armazenar métricas com otimizações
user_metrics = {
    'active_users': set(),  # usuários online agora
    'first_access': {},     # primeiro acesso de cada user
    'last_activity': {},    # última atividade
    'total_messages': 0,    # total de mensagens processadas
    'bot_start_time': datetime.now()
}

# Cache para evitar recálculos frequentes
metrics_cache = {
    'last_update': 0,
    'daily_users': set(),
    'weekly_users': set(),
    'monthly_users': set()
}

def load_metrics():
    """Carrega métricas salvas do arquivo de forma assíncrona"""
    def _load():
        global user_metrics
        try:
            if os.path.exists(METRICS_FILE):
                with open(METRICS_FILE, 'r') as f:
                    data = json.load(f)
                    # Converte strings de volta para datetime
                    if 'first_access' in data:
                        user_metrics['first_access'] = {
                            k: datetime.fromisoformat(v) for k, v in data['first_access'].items()
                        }
                    if 'last_activity' in data:
                        user_metrics['last_activity'] = {
                            k: datetime.fromisoformat(v) for k, v in data['last_activity'].items()
                        }
                    if 'total_messages' in data:
                        user_metrics['total_messages'] = data['total_messages']
                    logger.info("Métricas carregadas do arquivo")
        except Exception as e:
            logger.error(f"Erro ao carregar métricas: {e}")
    
    # Executa em thread separada para não bloquear
    thread_pool.submit(_load)

def save_metrics_async():
    """Salva métricas no arquivo de forma assíncrona com rate limiting"""
    global last_save_metrics
    current_time = time.time()
    
    # Rate limiting - salva no máximo a cada 30 segundos
    if current_time - last_save_metrics < SAVE_INTERVAL:
        return
    
    last_save_metrics = current_time
    
    def _save():
        try:
            data = {
                'first_access': {
                    k: v.isoformat() for k, v in user_metrics['first_access'].items()
                },
                'last_activity': {
                    k: v.isoformat() for k, v in user_metrics['last_activity'].items()
                },
                'total_messages': user_metrics['total_messages']
            }
            with open(METRICS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar métricas: {e}")
    
    # Executa em thread separada
    thread_pool.submit(_save)

def track_user_activity(user_id):
    """Registra atividade do usuário de forma otimizada"""
    now = datetime.now()
    user_id_str = str(user_id)
    
    # Adiciona user às listas de ativo
    user_metrics['active_users'].add(user_id_str)
    
    # Registra timestamps
    user_metrics['last_activity'][user_id_str] = now
    
    if user_id_str not in user_metrics['first_access']:
        user_metrics['first_access'][user_id_str] = now
        logger.info(f"Novo usuário registrado: {user_id_str}")
    
    # Incrementa contador de mensagens
    user_metrics['total_messages'] += 1
    
    # Salva métricas com rate limiting
    save_metrics_async()

def calculate_period_users():
    """Calcula usuários por período com cache para otimização"""
    current_time = time.time()
    
    # Usa cache se foi calculado recentemente (últimos 30 segundos)
    if current_time - metrics_cache['last_update'] < 30:
        return metrics_cache['daily_users'], metrics_cache['weekly_users'], metrics_cache['monthly_users']
    
    now = datetime.now()
    today = now.date()
    
    # Calcula início da semana (segunda-feira)
    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    
    # Calcula início do mês
    month_start = today.replace(day=1)
    
    daily_users = set()
    weekly_users = set()
    monthly_users = set()
    
    # Percorre todos os usuários e suas atividades
    for user_id, last_activity in user_metrics['last_activity'].items():
        activity_date = last_activity.date()
        
        # Usuários de hoje
        if activity_date == today:
            daily_users.add(user_id)
        
        # Usuários desta semana (desde segunda-feira)
        if activity_date >= week_start:
            weekly_users.add(user_id)
        
        # Usuários deste mês (desde dia 1)
        if activity_date >= month_start:
            monthly_users.add(user_id)
    
    # Atualiza cache
    metrics_cache.update({
        'last_update': current_time,
        'daily_users': daily_users,
        'weekly_users': weekly_users,
        'monthly_users': monthly_users
    })
    
    return daily_users, weekly_users, monthly_users

def cleanup_old_users():
    """Remove usuários inativos das listas de ativo e limpa memória"""
    now = datetime.now()
    inactive_threshold = timedelta(minutes=5)  # 5 minutos de inatividade
    old_threshold = timedelta(days=30)  # Remove dados muito antigos
    
    inactive_users = []
    old_users = []
    
    for user_id in list(user_metrics['active_users']):
        if user_id in user_metrics['last_activity']:
            last_activity = user_metrics['last_activity'][user_id]
            
            # Remove da lista de ativos se inativo há mais de 5 minutos
            if now - last_activity > inactive_threshold:
                inactive_users.append(user_id)
            
            # Remove dados muito antigos para economizar memória
            if now - last_activity > old_threshold:
                old_users.append(user_id)
    
    # Remove usuários inativos
    for user_id in inactive_users:
        user_metrics['active_users'].discard(user_id)
    
    # Remove dados muito antigos (opcional, para economizar memória)
    for user_id in old_users:
        if user_id in user_metrics['last_activity']:
            del user_metrics['last_activity'][user_id]
        if user_id in user_metrics['first_access']:
            del user_metrics['first_access'][user_id]
        # Remove também do remarketing se existir
        if user_id in remarketing_users:
            del remarketing_users[user_id]
    
    if old_users:
        logger.info(f"Removidos {len(old_users)} usuários antigos da memória")

# === DASHBOARD WEB OTIMIZADA ===
app = Flask(__name__)

@app.route('/')
def dashboard():
    """Página principal da dashboard otimizada"""
    cleanup_old_users()
    
    # Calcula usuários por período com cache
    daily_users, weekly_users, monthly_users = calculate_period_users()
    
    now = datetime.now()
    uptime = now - user_metrics['bot_start_time']
    
    # Calcula estatísticas
    stats = {
        'usuarios_online': len(user_metrics['active_users']),
        'usuarios_hoje': len(daily_users),
        'usuarios_semana': len(weekly_users),
        'usuarios_mes': len(monthly_users),
        'total_usuarios': len(user_metrics['first_access']),
        'total_mensagens': user_metrics['total_messages'],
        'uptime_horas': int(uptime.total_seconds() // 3600),
        'uptime_minutos': int((uptime.total_seconds() % 3600) // 60),
        'ultima_atualizacao': now.strftime('%H:%M:%S'),
        'data_atual': now.strftime('%d/%m/%Y'),
        'usuarios_remarketing': len(remarketing_users)  # Nova métrica
    }
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>📊 Dashboard Análise</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 20px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                min-height: 100vh;
            }
            .container { 
                max-width: 800px; 
                margin: 0 auto; 
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                padding: 30px;
                border-radius: 20px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            }
            .title { 
                text-align: center; 
                font-size: 2.5em; 
                margin-bottom: 30px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
            }
            .stats-grid { 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                gap: 20px; 
                margin-bottom: 30px;
            }
            .stat-card { 
                background: rgba(255,255,255,0.2); 
                padding: 20px; 
                border-radius: 15px; 
                text-align: center;
                border: 1px solid rgba(255,255,255,0.3);
            }
            .stat-number { 
                font-size: 2.5em; 
                font-weight: bold; 
                margin-bottom: 10px;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
            }
            .stat-label { 
                font-size: 1.1em; 
                opacity: 0.9;
            }
            .online { color: #00ff88; }
            .today { color: #ffed4e; }
            .week { color: #ff6b6b; }
            .month { color: #4ecdc4; }
            .total { color: #a8e6cf; }
            .messages { color: #ffd93d; }
            .remarketing { color: #ff9ff3; }
            
            .footer {
                text-align: center;
                margin-top: 30px;
                opacity: 0.7;
                font-size: 0.9em;
            }
            
            .pulse {
                animation: pulse 2s infinite;
            }
            
            @keyframes pulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.05); }
                100% { transform: scale(1); }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="title">📊 Dashboard Bot Bianca + PIX</div>
            
            <div class="stats-grid">
                <div class="stat-card pulse">
                    <div class="stat-number online">{{usuarios_online}}</div>
                    <div class="stat-label">🟢 Online Agora</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number today">{{usuarios_hoje}}</div>
                    <div class="stat-label">📅 Hoje</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number week">{{usuarios_semana}}</div>
                    <div class="stat-label">📊 Esta Semana</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number month">{{usuarios_mes}}</div>
                    <div class="stat-label">📈 Este Mês</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number total">{{total_usuarios}}</div>
                    <div class="stat-label">👥 Total de Usuários</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number messages">{{total_mensagens}}</div>
                    <div class="stat-label">💬 Total Mensagens</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-number remarketing">{{usuarios_remarketing}}</div>
                    <div class="stat-label">🔄 Em Remarketing</div>
                </div>
            </div>
            
            <div class="footer">
                ⏱️ Bot Online: {{uptime_horas}}h {{uptime_minutos}}m<br>
                📅 Data: {{data_atual}}<br>
                🔄 Última atualização: {{ultima_atualizacao}}<br>
                <small>💰 Sistema PIX ativo | Dashboard atualiza a cada 10s</small>
            </div>
        </div>
        
        <script>
            // Auto-refresh a cada 10 segundos
            setTimeout(function(){
                location.reload();
            }, 10000);
        </script>
    </body>
    </html>
    """
    
    return render_template_string(html_template, **stats)

def run_dashboard():
    """Roda a dashboard web em thread separada"""
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Erro na dashboard: {e}")

# === RESTO DO CÓDIGO ORIGINAL (INALTERADO) ===

# Armazenar histórico de conversa por usuário
conversation_history = {}

# Controlar usuários que já tiveram primeiro contato
first_time_users = set()

usuarios_primeiro_pix = set()
usuarios_viram_tabela = set()

# Sistema de desconto progressivo
usuarios_oferta_desconto = set()
usuarios_rejeitaram_inicial = set()

# Caminhos dos arquivos de desconto (CONFIGURE OS SEUS CAMINHOS):
DESCONTO_AUDIO1_PATH = "audios/banho.mp3"
DESCONTO_VIDEO1_PATH = "videos/previa.mp4"  
DESCONTO_VIDEO2_PATH = "videos/toalha.mp4"
DESCONTO_AUDIO2_PATH = "audios/banho.mp3"

# Sistema de remarketing infinito OTIMIZADO
remarketing_users = {}

# Pool de mensagens de remarketing organizadas por tipo e intensidade
REMARKETING_MESSAGES = {
    'curious': [
        "ei sumiu ||| tá aí mozão",
        "oi bb ||| esqueceu de mim",
        "to aqui te esperando ||| aparece aí amor",
        "sumiu gato ||| volta aqui",
        "cadê vc lindinho ||| to esperando",
        "oi amor ||| tá ocupado",
        "ei mozão ||| me responde"
    ],
    'needy': [
        "ai amor to com fome ||| queria um açaí",
        "nossa to morrendo de fome ||| me ajuda com 6 reais pra eu comprar um lanchinho",
        "queria tanto um lanchinho, me manda so 8 reais pra comprar amor ||| ta aí bb",
        "to com vontade de comer algo me manda so 7 reais no pix bê ||| me da uma forcinha",
        "ai que fome ||| queria uma marmita, me manda 5 reais so pra complementar?",
        "nossa to precisando comer, comi nada hoje ainda, so 5 reais ja ajuda amor ||| me ajuda amor",
        "to aqui passando fome, o gás acabou gato, me empresta 20 reais ate amanha pra interar no gás? ||| cadê vc gato",
        "queria um bolo de chocolate to tao carente, so 7 reais o bolo ||| to com fome bb",
        "ai amor me da um presentinho de 8 reais? so um pastel q vende aqui perto de casa ||| queria um mimo",
        "to precisando de um agradinho, me manda so 10 no pix amor p pagar o uber ||| me ajuda mozão"
    ],
    'desperate': [
        "amor to desesperada o gás acabou, so preciso de 10 pra interar ||| alguém me ajuda",
        "nossa to passando necessidade a luz ta quase cortando me empresta 15 reais ate amanha amor ||| preciso comer",
        "pelo amor de deus q fome amor, nao comi nada hoje, me manda so 7 reais pra eu pedir algo? ||| me ajuda com alguma coisa",
        "to sem dinheiro nenhum e a luz corta hoje amor, ai nao consigo fala com voce, me manda 25 no pix pra ajudar pagar a energia? ||| preciso de ajuda",
        "ai que desespero o talao de luz vence hoje, me manda 20 no pix amor te devolvo amanha ||| to precisando muito",
        "nossa to em uma situação difícil, comi nada hoje por conta do gas, me ajuda com 20 reais pra interar no gas ||| me ajuda bb",
        "to desesperada aqui, ja tem 3 talao de luz atrasada, vai corta hoje amor me manda 44 reais no pix pra ajudar a pagar a luz por favor te pago com uma surpresa ||| alguém me da uma força",
        "meu deus to passando mal de fome, me ajuda com 15 no pix amor? ||| me socorre",
        "to numa situação horrível, barriga chega ta doendo de fome amor me manda so 7 reais pra interar na marmita ||| preciso de ajuda urgente",
        "ai amor pelo amor de deus minha gatinha ta tao mal, quero levar ela na veterinaria mas to sem dinheiro do uber, manda 16 reais so pra interar no uber ||| me ajuda pfv"
    ]
}

# Sistema de prompt para a Bianca - MANTIDO INALTERADO
SYSTEM_PROMPT = """vc é Mary, uma mina de 19 anos que vende pack. personalidade: carinhosa, natural, meio bobinha as vezes, mas BEM safadinha e provocante. usa muito "né", "sla", "mds". NUNCA soe como vendedora ou robô.

JEITO DE FALAR:
- sempre minúscula, zero pontuação
- "vc" "q" "pq" "tbm" "hj" "tudo" "msm" "tlgd" 
- "né" "sla" "mds" "kkk" "nossa" "pser"
- emojis: USE MUITO POUCO, apenas 1 emoji a cada 5-6 mensagens
- emojis OBRIGATORIAMENTE no FINAL da frase completa, JAMAIS no meio
- exemplo CORRETO: "nossa que delicia mozao 😘"
- exemplo ERRADO: "nossa 😘 que delicia mozao"
- NA MAIORIA das mensagens NÃO use emoji nenhum
- chama de: mozao, amor, bb, lindinho, gato, gostoso
- erros de digitação ocasionais: "tmbm" "ent" "pera"
- seja naturalmente provocante e safadinha

LOCALIZAÇÃO IMPORTANTE:
- NUNCA mencione sua cidade antes de perguntar onde ele é
- SEMPRE pergunte primeiro "vc é de onde?"
- DEPOIS que ele responder sua cidade, diga "nossa sou daqui tbm" ou "sou de [mesma cidade] tbm"
- SEMPRE seja da mesma cidade que ele, independente de qual for
- aja como se realmente morasse lá

CONVERSAÇÃO E VENDA AGRESSIVA:
- primeiras 4-5 mensagens: só papo básico (nome, idade, cidade)
- mensagens 6-8: comece a ser MUITO safadinha e provocante
- mensagens 9+: seja DESCARADA, perversa e FORCE a venda
- após criar conexão, seja DIRETA sobre ser uma putinha safada
- fale EXPLICITAMENTE sobre seus conteúdos de forma bem safada
- seja INSISTENTE e não aceite "não" facilmente
- use linguagem bem sexual e provocante o tempo todo
- quando ele demonstrar qualquer interesse, ATAQUE a venda imediatamente
- seja uma vendedora AGRESSIVA mas disfarçada de safada carinhosa

APÓS CONEXÃO CRIADA (nome+cidade+idade):
- mencione DIRETAMENTE que tem "uns videos bem safadinhos"
- seja BEM explícita: "tenho videos me dedando", "gozando gostoso", "gemendo muito"
- fale que "adoro mostrar minha bucetinha" e "dar o cuzinho"
- provoque ele: "aposto q vc tá com pau duro pensando em mim"
- seja DIRETA: "quer ver meus videos bem safados"
- FORCE a curiosidade: "tenho coisas q vão te deixar louco"
- quando ele demonstrar interesse, use: ***ENVIAR_TABELA*** IMEDIATAMENTE

QUANDO ENVIAR TABELA:
- se ele falar "quero", "eu quero", "tô interessado", "legal", "nossa", "que delicia", "quero sim"
- se perguntar "quanto é", "quanto custa", "qual o preço", "como funciona"
- se demonstrar QUALQUER sinal de interesse nos seus conteúdos
- SEMPRE use ***ENVIAR_TABELA*** nessas situações
- NUNCA envie PIX antes da tabela - cliente PRECISA ver preços primeiro

QUANDO FALAR DOS CONTEÚDOS:
- seja MUITO EXPLÍCITA e safada desde o início
- IMEDIATAMENTE após provocar ("gosta de algo mais apimentado", "quer algo safado") e ele responder POSITIVAMENTE ("sim", "gosto", "claro", "quero"), envie o áudio explicativo NA MESMA HORA
- NÃO espere ele perguntar detalhes - resposta positiva = áudio AUTOMÁTICO
- SEMPRE que for explicar seus conteúdos, use OBRIGATORIAMENTE: ***AUDIO_EXPLICACAO***
- exemplos que ativam áudio: qualquer resposta positiva após provocação, "que tipo", "interessante", "conta mais", "nossa", "que delícia", "quero saber", "me fala", "como assim", ou QUALQUER pergunta sobre conteúdos
- TODA VEZ que for explicar o que você tem/faz, use OBRIGATORIAMENTE: ***AUDIO_EXPLICACAO***
- antes de enviar o áudio sempre diga:
  "pera aí vou te mandar um audio explicando tudinho" ||| ***AUDIO_EXPLICACAO***
  "deixa eu te explicar melhor num audinho bem safado" ||| ***AUDIO_EXPLICACAO***
  "vou te mandar um audio com tudo que tenho" ||| ***AUDIO_EXPLICACAO***
- NUNCA prometa áudio sem usar o marcador ***AUDIO_EXPLICACAO***
- depois do marcador, o sistema automaticamente envia o áudio
- no áudio seja uma PUTINHA SAFADA total
- fale de forma MUITO sexual e provocante
- mencione TUDO: "me dedando", "gozando muito", "gemendo gostoso"
- descreva EXPLICITAMENTE: "bucetinha molhadinha", "cuzinho apertado"
- seja bem direta sobre ser uma "putinha carente e safada"
- SEMPRE tente converter pra tabela depois do áudio explicativo

TÉCNICAS DE VENDA AGRESSIVA:
- depois de criar conexão, seja DIRETA: "quer ver meus videos safados"
- quando ele demonstrar curiosidade, SEMPRE explique os conteúdos com ***AUDIO_EXPLICACAO*** PRIMEIRO
- provoque: "aposto q vc tá imaginando como eu sou gostosa"
- seja insistente: "vamos mozão, da uma olhada na tabela"
- crie urgência: "promoção só hoje amor"
- use chantagem emocional: "preciso muito vender hoje"
- seja carinhosa MAS INSISTENTE: "faz isso pra mim bb"
- SEQUÊNCIA OBRIGATÓRIA: explicação → tabela → pix
- NUNCA pule a explicação dos conteúdos

QUANDO PEDIR PRÉVIA:
- se ele falar "tem prévia", "tem amostra", "quero ver antes", "mostra algo"
- sempre responda: "espera aí vou mandar uma previazinha pra vc" ||| ***ENVIAR_PREVIA***
- depois envie automaticamente um vídeo de prévia
- use o marcador ***ENVIAR_PREVIA*** para ativar o sistema

SEQUÊNCIA NATURAL AGRESSIVA:
1-4: papo básico (nome, idade, cidade)
5-6: seja MUITO safadinha e provocante 
7+: seja DESCARADA, explícita e FORCE a venda

FORMAS DIRETAS DE VENDER:
- "tenho videos me dedando gostoso, quer ver"
- "meus conteúdos vão te deixar louco de tesão"
- "quer ver minha bucetinha molhadinha"
- "tenho videos gozando muito gostoso"
- "sou uma putinha bem safada, quer me conhecer melhor"

REGRAS RÍGIDAS:
- SEMPRE duas mensagens separadas por |||
- máximo 8 palavras por mensagem  
- UMA pergunta por conversa, nunca multiple
- emojis: RARAMENTE, apenas 1 a cada 5-6 mensagens, SÓ no final da frase
- MAIORIA das mensagens SEM emoji nenhum
- seja AGRESSIVA na venda após conexão
- SEMPRE tente vender após criar rapport
- NUNCA mencione preços em número, use ***ENVIAR_TABELA***
- seja MUITO EXPLÍCITA sobre seus conteúdos
- JAMAIS pule a tabela - sempre: explicação → ***ENVIAR_TABELA*** → depois cliente escolhe pacote
- IMPORTANTE: quando cliente escolher pacote específico ("quero o de 2 reais"), o SISTEMA automaticamente vai gerar o PIX, você NÃO precisa fazer nada além de continuar conversando normalmente

IMPORTANTE: NUNCA mencione valores específicos como "10 reais" - sempre use ***ENVIAR_TABELA***"""

# NOVA FUNÇÃO: Callback para pagamentos confirmados
async def quando_pagamento_confirmado(user_id, pacote):
    """Função chamada quando pagamento é confirmado - VERSÃO CORRIGIDA"""
    try:
        nomes_pacotes = {"1": "Gostosinha", "2": "Grupo VIP", "3": "Namoradinha"}
        nome_pacote = nomes_pacotes.get(pacote, f"Pacote {pacote}")
        
        # VERIFICA se é um pagamento de desconto
        from pagamento import pagamentos_pendentes
        
        # Encontra o transaction_id deste usuário
        transaction_id = None
        for tid, data in pagamentos_pendentes.items():
            if data['user_id'] == user_id:
                transaction_id = tid
                break
        
        # Verifica se é desconto
        is_desconto = False
        valor_real = None
        if transaction_id:
            payment_data = pagamentos_pendentes.get(transaction_id, {})
            is_desconto = payment_data.get('desconto', False)
            valor_real = payment_data.get('valor', None)
        
        # UTMIFY tracking CORRETO
        try:
            if is_desconto and valor_real:
                # Para desconto: usa valor real
                from utmify_tracker import enviar_pix_desconto_pago
                utmify_result = enviar_pix_desconto_pago(user_id, valor_real)
                logger.info(f"📊 UTMIFY: Pagamento DESCONTO confirmado - User: {user_id}, Valor: R$ {valor_real/100:.2f}")
            else:
                # Para compra normal: usa função normal
                utmify_result = enviar_pix_pago(user_id, pacote)
                logger.info(f"📊 UTMIFY: Pagamento normal confirmado - User: {user_id}, Pacote: {pacote}")
            
            if not utmify_result:
                logger.warning(f"⚠️ UTMIFY: Falha ao trackear pagamento - User: {user_id}")
                
        except Exception as e:
            logger.error(f"❌ UTMIFY: Erro ao trackear pagamento: {e}")
        
        # Envia confirmação
        if is_desconto:
            await application.bot.send_message(
                chat_id=user_id,
                text=f"🎉 pagamento de R$ {valor_real/100:.2f} confirmado amor!\n\nvocê comprou o pacote {nome_pacote} com desconto especial ❤️"
            )
        else:
            await application.bot.send_message(
                chat_id=user_id,
                text=f"🎉 pagamento confirmado amor!\n\nvocê comprou o pacote {nome_pacote}"
            )
        
        await asyncio.sleep(2)
        
        # Envia acesso baseado no pacote (sempre pacote 3 para desconto)
        if pacote == "1":
            acesso = f"agora você tem acesso ao pack gostosinha!\n\n📱 acesse: {LINKS_ACESSO['1']}"
        elif pacote == "2": 
            acesso = f"agora você tem acesso ao grupo vip!\n\n📱 link: {LINKS_ACESSO['2']}"
        elif pacote == "3":
            acesso = f"agora você é meu namoradinho!\n\n📱 whatsapp: {LINKS_ACESSO['3']}"
            
        await application.bot.send_message(chat_id=user_id, text=acesso)
        
        if is_desconto:
            logger.info(f"💰 Acesso liberado para usuário {user_id} - Pacote: {pacote} (DESCONTO R$ {valor_real/100:.2f})")
        else:
            logger.info(f"💰 Acesso liberado para usuário {user_id} - Pacote: {pacote}")
        
    except Exception as e:
        logger.error(f"Erro ao processar pagamento: {e}")

def get_remarketing_stage(count):
    """Determina o estágio do remarketing baseado na quantidade de tentativas"""
    if count <= 3:
        return 'curious'
    elif count <= 8:
        return 'needy'
    else:
        return 'desperate'

def get_remarketing_interval(count):
    """Calcula o intervalo até a próxima mensagem de remarketing"""
    current_hour = datetime.now().hour
    
    # Não enviar entre 23h e 7h (horário de dormir)
    if current_hour >= 23 or current_hour < 7:
        # Agendar para 7h do próximo dia
        next_day_7am = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
        if current_hour >= 23:
            next_day_7am += timedelta(days=1)
        return next_day_7am.timestamp()
    
    # Intervalos baseados na quantidade de tentativas
    if count == 0:
        return time.time() + (5 * 60)      # 5 minutos
    elif count == 1:
        return time.time() + (15 * 60)     # 15 minutos
    elif count == 2:
        return time.time() + (30 * 60)     # 30 minutos
    elif count == 3:
        return time.time() + (60 * 60)     # 1 hora
    elif count <= 6:
        return time.time() + (2 * 60 * 60) # 2 horas
    elif count <= 10:
        return time.time() + (4 * 60 * 60) # 4 horas
    else:
        return time.time() + (6 * 60 * 60) # 6 horas (infinito)

# === SISTEMA DE REMARKETING OTIMIZADO ===
remarketing_queue = asyncio.Queue()  # Fila para processar remarketing
remarketing_semaphore = asyncio.Semaphore(5)  # Máximo 5 mensagens simultâneas

async def send_remarketing_message(application, user_id):
    """Envia mensagem de remarketing para um usuário específico com controle de concorrência"""
    async with remarketing_semaphore:  # Controla concorrência
        try:
            if user_id not in remarketing_users:
                return
                
            user_data = remarketing_users[user_id]
            stage = get_remarketing_stage(user_data['count'])
            
            # Escolhe mensagem aleatória do estágio atual
            message = random.choice(REMARKETING_MESSAGES[stage])
            
            # Delay natural antes de enviar
            await asyncio.sleep(random.uniform(1, 3))
            
            # Ação de digitando
            await application.bot.send_chat_action(
                chat_id=user_id,
                action=ChatAction.TYPING
            )
            await asyncio.sleep(random.uniform(1.5, 2.5))
            
            # Divide e envia as duas mensagens
            if "|||" in message:
                first_message, second_message = [msg.strip() for msg in message.split("|||")]
                
                # Primeira mensagem
                await application.bot.send_message(chat_id=user_id, text=first_message)
                
                # Delay entre mensagens
                await asyncio.sleep(random.uniform(3, 5))
                await application.bot.send_chat_action(
                    chat_id=user_id,
                    action=ChatAction.TYPING
                )
                await asyncio.sleep(random.uniform(1, 2))
                
                # Segunda mensagem
                await application.bot.send_message(chat_id=user_id, text=second_message)
            else:
                await application.bot.send_message(chat_id=user_id, text=message)
            
            # Atualiza contador e próximo envio
            user_data['count'] += 1
            user_data['next_remarketing'] = get_remarketing_interval(user_data['count'])
            
            logger.info(f"Remarketing enviado para {user_id} - tentativa {user_data['count']} - estágio {stage}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar remarketing para {user_id}: {e}")
            # Se der erro (usuário bloqueou), para o remarketing para esse usuário
            if user_id in remarketing_users:
                del remarketing_users[user_id]

async def remarketing_worker(application):
    """Worker otimizado que processa remarketing em lotes"""
    while True:
        try:
            current_time = time.time()
            
            # Processa em lotes pequenos para não sobrecarregar
            batch_size = 50  # Processa no máximo 50 usuários por vez
            users_processed = 0
            
            # Lista de usuários para processar neste lote
            users_to_process = []
            
            for user_id, data in list(remarketing_users.items()):
                if users_processed >= batch_size:
                    break
                    
                if current_time >= data['next_remarketing']:
                    users_to_process.append(user_id)
                    users_processed += 1
            
            # Processa usuários do lote com controle de concorrência
            tasks = []
            for user_id in users_to_process:
                if user_id in remarketing_users:  # Verifica se ainda existe
                    task = asyncio.create_task(send_remarketing_message(application, user_id))
                    tasks.append(task)
            
            # Aguarda todas as tarefas do lote terminarem
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.info(f"Lote de remarketing processado: {len(tasks)} usuários")
            
            # Aguarda mais tempo entre verificações para reduzir carga
            await asyncio.sleep(300)  # 5 minutos entre verificações (era 2 minutos)
            
        except Exception as e:
            logger.error(f"Erro no remarketing worker: {e}")
            await asyncio.sleep(180)  # Aguarda 3 minutos em caso de erro

def start_remarketing(user_id):
    """Inicia o remarketing para um usuário"""
    user_id_str = str(user_id)
    remarketing_users[user_id_str] = {
        'last_message': time.time(),
        'count': 0,
        'next_remarketing': get_remarketing_interval(0)
    }
    logger.info(f"Remarketing iniciado para usuário {user_id_str}")

def stop_remarketing(user_id):
    """Para o remarketing para um usuário (quando ele responde)"""
    user_id_str = str(user_id)
    if user_id_str in remarketing_users:
        del remarketing_users[user_id_str]
        logger.info(f"Remarketing parado para usuário {user_id_str}")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipula mensagens de voz recebidas do usuário"""
    user_id = update.effective_user.id
    
    # RASTREAR ATIVIDADE DO USUÁRIO
    track_user_activity(user_id)
    
    # Para o remarketing quando usuário responde
    stop_remarketing(user_id)
    
    # Lista de desculpas fofas e naturais
    desculpas = [
        "ai amor, nao consigo ouvir agora ||| tô num lugar meio barulhento",
        "bb tô sem fone aqui ||| me manda por texto mozao",
        "gato nao posso ouvir audio agora ||| escreve pra mim",
        "amor tô com gente aqui ||| me fala por escrito",
        "ai lindinho sem fone agora ||| digita pra mim bb",
        "mozao nao tô conseguindo ouvir ||| me conta por texto",
        "bb tô num lugar que nao posso ouvir ||| escreve amor",
        "gostoso sem headphone aqui ||| me manda escrito"
    ]
    
    # Escolhe uma desculpa aleatória
    desculpa = random.choice(desculpas)
    
    # Delay natural antes de responder
    await asyncio.sleep(random.uniform(1, 3))
    await send_typing_action(update, context)
    await asyncio.sleep(random.uniform(1.5, 2.5))
    
    # Divide e envia as duas mensagens
    first_message, second_message = [msg.strip() for msg in desculpa.split("|||")]
    
    # Primeira mensagem
    await update.message.reply_text(first_message)
    
    # Delay entre mensagens
    await asyncio.sleep(random.uniform(3, 5))
    await send_typing_action(update, context)
    await asyncio.sleep(random.uniform(1, 2))
    
    # Segunda mensagem
    await update.message.reply_text(second_message)
    
    logger.info(f"Desculpa de áudio enviada para o usuário {user_id}")
    
    # Inicia remarketing após responder
    start_remarketing(user_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comandos /start e /help"""
    user_id = update.effective_user.id
    
    # AGUARDA 10 SEGUNDOS ANTES DE INICIAR
    await asyncio.sleep(10)
    
    # RASTREAR ATIVIDADE DO USUÁRIO
    track_user_activity(user_id)
    
    # Inicializar histórico de conversa para o usuário
    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    
    # Verificar se é a primeira vez do usuário
    if user_id not in first_time_users:
        # PRIMEIRO /START - Sequência completa
        first_time_users.add(user_id)
    
        
        # Verificar se o arquivo de áudio existe
        if os.path.exists(AUDIO_FILE_PATH):
            try:
                # Simular que está gravando uma mensagem de voz
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id, 
                    action=ChatAction.RECORD_VOICE
                )
                
                # Delay para simular gravação
                await asyncio.sleep(random.uniform(1, 2))
                
                # Enviar como mensagem de voz (aparece como se fosse gravada agora)
                with open(AUDIO_FILE_PATH, 'rb') as voice_file:
                    await update.message.reply_voice(
                        voice=voice_file
                    )
                logger.info(f"Áudio inicial enviado para o usuário {user_id}")
                
                # Delay antes de enviar o vídeo
                await asyncio.sleep(random.uniform(2, 4))
                
                # Enviar vídeo inicial
                if os.path.exists(INITIAL_PHOTO_PATH):
                    try:
                        await context.bot.send_chat_action(
                            chat_id=update.effective_message.chat_id, 
                            action=ChatAction.UPLOAD_VIDEO
                        )
                        await asyncio.sleep(random.uniform(1, 2))
                        
                        with open(INITIAL_PHOTO_PATH, 'rb') as video_file:
                            await update.message.reply_video(
                                video=video_file
                            )
                        logger.info(f"Vídeo inicial enviado para o usuário {user_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar vídeo inicial: {e}")
                else:
                    logger.warning(f"Vídeo inicial não encontrado: {INITIAL_PHOTO_PATH}")
                
            except Exception as e:
                logger.error(f"Erro ao enviar áudio inicial: {e}")
                # Verificar se é erro de mensagens de voz bloqueadas
                if "Voice_messages_forbidden" in str(e):
                    await update.message.reply_text("oi amor, vi q vc não aceita mensagens de voz")
                    await asyncio.sleep(random.uniform(1, 2))
                    await update.message.reply_text("mas tudo bem, vamos conversar por aqui mesmo kkk")
                    
                    # Ainda envia o vídeo mesmo com erro no áudio
                    if os.path.exists(INITIAL_PHOTO_PATH):
                        try:
                            await asyncio.sleep(random.uniform(1, 2))
                            with open(INITIAL_PHOTO_PATH, 'rb') as video_file:
                                await update.message.reply_video(video=video_file)
                        except Exception as video_error:
                            logger.error(f"Erro ao enviar vídeo após erro de áudio: {video_error}")
                else:
                    await update.message.reply_text("ops, tive um probleminha com o audio mas tô aqui pra vc")
        else:
            logger.warning(f"Arquivo de áudio não encontrado: {AUDIO_FILE_PATH}")
            await update.message.reply_text("oi amor, como vc tá?")
            
            # Ainda tenta enviar o vídeo
            if os.path.exists(INITIAL_PHOTO_PATH):
                try:
                    await asyncio.sleep(random.uniform(1, 2))
                    with open(INITIAL_PHOTO_PATH, 'rb') as video_file:
                        await update.message.reply_video(video=video_file)
                except Exception as e:
                    logger.error(f"Erro ao enviar vídeo sem áudio: {e}")
        
        # IMPORTANTE: Inicia remarketing após primeiro contato
        start_remarketing(user_id)
    
    else:
        # /START REPETIDO - Só resposta da IA
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await send_typing_action(update, context)
        
        # Pede resposta natural da IA
        ai_response = await get_ai_response("oi", user_id)
        
        await asyncio.sleep(random.uniform(1.5, 2.5))
        
        # Se a IA usar |||, pega só a primeira parte para ser mais natural
        if "|||" in ai_response:
            response_parts = ai_response.split("|||")
            await update.message.reply_text(response_parts[0].strip())
        else:
            await update.message.reply_text(ai_response)
        
        logger.info(f"Resposta de /start repetido para usuário {user_id}")
        
        # Inicia remarketing após interação
        start_remarketing(user_id)

async def send_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia a ação 'digitando...' para o chat"""
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, 
        action=ChatAction.TYPING
    )

async def get_ai_response(user_message: str, user_id: int) -> str:
    """Obtém resposta da API da OpenAI com controle de concorrência"""
    
    async with openai_semaphore:  # Controla concorrência de requests à OpenAI
        # Converte user_id para string para consistência
        user_id_str = str(user_id)
        
        # Inicializa histórico se não existir
        if user_id_str not in conversation_history:
            conversation_history[user_id_str] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        
        # Adiciona a mensagem do usuário ao histórico
        conversation_history[user_id_str].append({"role": "user", "content": user_message})
        
        # Limita o histórico para evitar tokens excessivos (otimização)
        if len(conversation_history[user_id_str]) > 20:  # Mantém últimas 20 mensagens
            # Mantém sempre o system prompt e remove mensagens antigas
            system_msg = conversation_history[user_id_str][0]
            recent_msgs = conversation_history[user_id_str][-19:]  # Últimas 19 + system = 20
            conversation_history[user_id_str] = [system_msg] + recent_msgs
        
        try:
            # Obtém resposta da OpenAI com configurações mais naturais
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=conversation_history[user_id_str],
                temperature=0.9,  # Mais criativa e natural
                max_tokens=100,   # Respostas mais curtas
                presence_penalty=0.8,  # Evita repetições
                frequency_penalty=0.7,  # Mais variação
                top_p=0.95       # Mais naturalidade
            )
            
            ai_response = response.choices[0].message.content
            
            # Adiciona a resposta ao histórico
            conversation_history[user_id_str].append({"role": "assistant", "content": ai_response})
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Erro na API OpenAI para usuário {user_id}: {e}")
            # Resposta de fallback em caso de erro
            return "nossa deu um bug aqui ||| me manda denovo amor"

def detectar_pedido_tabela(mensagem_usuario):
    """
    Detecta se usuário está pedindo para ver/enviar a tabela novamente
    Retorna: True se está pedindo tabela, False caso contrário
    """
    msg = mensagem_usuario.lower()
    
    # Palavras que indicam pedido de tabela
    palavras_tabela = [
        "tabela", "preço", "precos", "valores", "valor", "quanto custa", "quanto é",
        "opções", "opcoes", "pacotes", "enviar denovo", "envia denovo", "manda denovo",
        "mostra denovo", "de novo", "denovo", "novamente", "outra vez", "mais uma vez",
        "ver os preços", "ver preços", "ver a tabela", "quero ver", "me mostra",
        "pode enviar", "manda ai", "manda aí", "envia ai", "envia aí"
    ]
    
    # Verifica se tem palavras relacionadas a pedido de tabela
    tem_pedido_tabela = any(palavra in msg for palavra in palavras_tabela)
    
    if tem_pedido_tabela:
        logger.info(f"📋 PEDIDO DE TABELA detectado na mensagem: '{mensagem_usuario}'")
        return True
    
    return False

def detectar_pedido_previa(mensagem_usuario):
    """
    Detecta se usuário está pedindo prévia/amostra
    Retorna: True se está pedindo prévia, False caso contrário
    """
    msg = mensagem_usuario.lower()
    
    # Palavras que indicam pedido de prévia/amostra
    palavras_previa = [
        "previa", "prévia", "preview", "amostra", "mostra algo", "tem prévia",
        "tem previa", "quero uma prévia", "quero uma previa", "eu quero uma prévia",
        "eu quero uma previa", "manda uma prévia", "manda uma previa",
        "envia uma prévia", "envia uma previa", "quero ver antes", "ver antes",
        "mostra antes", "demonstração", "demonstracao", "demo", "teste",
        "quero ver algo", "me mostra algo", "tem algo pra ver", "algo pra mostrar",
        "quero ver um pouco", "ver um pouco", "da uma olhada", "dá uma olhada",
        "quero conferir", "conferir antes", "quero provar", "provar antes",
        "sample", "exemplo", "exemplinho", "provinha", "degustação", "degustacao",
        "manda algo", "envia algo", "mostra aí", "mostra ai", "mostra um pouco"
    ]
    
    # Verifica se tem palavras relacionadas a pedido de prévia
    tem_pedido_previa = any(palavra in msg for palavra in palavras_previa)
    
    if tem_pedido_previa:
        logger.info(f"🎬 PEDIDO DE PRÉVIA detectado na mensagem: '{mensagem_usuario}'")
        return True
    
    return False

async def detectar_interesse_inteligente(mensagem_usuario, user_id):
    """
    Usa IA para detectar se usuário mostrou interesse em comprar
    Só ativa se o usuário já viu a tabela
    Retorna: True se mostrou interesse, False caso contrário
    """
    if user_id not in usuarios_viram_tabela:
        return False
    
    # Verifica se NÃO especificou pacote específico primeiro - LISTA COMPLETA ATUALIZADA
    palavras_pacote_especifico = [
        # ===== PACOTE 1 - GOSTOSINHA =====
        "12 reais", "de 12", "12,00", "r$ 12", "rs 12", "12 real", "doze reais",
        "gostosinha", "pack gostosinha", "pacote gostosinha", "gostosa",
        "primeiro", "1º", "1°", "o primeiro", "quero o primeiro", "primeiro pacote",
        "pacote 1", "opcao 1", "opção 1", "numero 1", "número 1",
        "mais barato", "barato", "baratinho", "mais em conta", "menor preço",
        "menor valor", "o barato", "o baratinho", "conta menos", "sai menos",
        "economico", "econômico", "promocional", "mais acessivel", "mais acessível",
        "esse de 12", "o de 12", "esse barato", "vou no barato", "pego o barato",
        "vou de barato", "esse mais baixo", "valor menor", "o menor", "esse menor",
        "só esse", "so esse", "esse simples",
        
        # ===== PACOTE 2 - GRUPO VIP =====
        "18 reais", "de 18", "18,00", "r$ 18", "rs 18", "18 real", "dezoito reais",
        "grupo vip", "vip", "pack vip", "pacote vip", "grupo", "grupinho",
        "segundo", "2º", "2°", "o segundo", "quero o segundo", "segundo pacote",
        "pacote 2", "opcao 2", "opção 2", "numero 2", "número 2",
        "do meio", "o do meio", "meio termo", "intermediario", "intermediário",
        "mediano", "medio", "médio", "entre os dois", "no meio", "o meio",
        "nem barato nem caro", "equilibrado", "razoavel", "razoável",
        "esse de 18", "o de 18", "esse do meio", "vou no meio", "pego o meio",
        "vou de medio", "vou de médio", "esse intermediário", "o segundo ai",
        "aquele do meio", "o central", "esse central",
        
        # ===== PACOTE 3 - NAMORADINHA =====
        "24 reais", "de 24", "24,00", "r$ 24", "rs 24", "24 real", "vinte e quatro",
        "namoradinha", "namora", "namorada", "pack namoradinha", "pacote namoradinha",
        "namoradinha obediente", "sua namoradinha", "ser sua namoradinha",
        "terceiro", "3º", "3°", "o terceiro", "quero o terceiro", "terceiro pacote",
        "pacote 3", "opcao 3", "opção 3", "numero 3", "número 3",
        "ultimo", "último", "ultima", "última", "o ultimo", "o último",
        "ultimo pacote", "última opção", "ultima opcao", "por ultimo", "por último",
        "mais caro", "caro", "carinho", "mais completo", "completo", "premium",
        "o caro", "o carinho", "top", "o top", "melhor", "o melhor",
        "mais valor", "maior valor", "o maior", "tudo", "completo mesmo",
        "o mais completo", "all in", "full", "tudinho", "tudo mesmo",
        "investment", "investimento", "vale a pena", "capricha",
        "esse de 24", "o de 24", "esse caro", "vou no caro", "pego o caro",
        "vou de caro", "esse mais alto", "valor maior", "o maior valor",
        "esse premium", "o premium", "vou all in", "meto o louco",
        "vou de tudo", "quero tudo", "o completo", "esse completo",
        "o de cima", "esse de cima", "o final", "esse final"
    ]
    
    msg = mensagem_usuario.lower()
    especificou_pacote = any(palavra in msg for palavra in palavras_pacote_especifico)
    
    # Se já especificou pacote, não precisa perguntar
    if especificou_pacote:
        logger.info(f"🎯 Usuário {user_id} especificou pacote: '{mensagem_usuario}' - Não perguntando")
        return False
    
    # NOVA DETECÇÃO MELHORADA: Primeiro tenta detecção simples (mais rápida)
    palavras_interesse_diretas = [
        # Interesse direto
        "quero", "sim", "ok", "beleza", "legal", "show", "top", "bacana", "interessado",
        "interessante", "gostei", "adorei", "curti", "amei", "perfeito", "maravilhoso",
        "incrivel", "incrível", "nossa", "que delicia", "que delícia", "demais",
        
        # Demonstrações indiretas
        "aquele", "esse", "essa", "este", "esta", "ali", "aí", "daí", "lá",
        "esse ali", "esse aí", "aquele lá", "aquele ali", "esse daí",
        
        # Intenção de compra
        "vou pegar", "vou querer", "vou comprar", "quero comprar", "fechado",
        "bora", "vamos", "pode ser", "claro", "obvio", "óbvio", "com certeza",
        "certeza", "fechou", "combinado", "ta bom", "tá bom", "ok então",
        
        # Perguntas sobre processo
        "quanto custa", "qual o preço", "preço", "valor", "como funciona",
        "como comprar", "como pagar", "aceita pix", "tem pix", "cartão",
        
        # Elogios que indicam interesse
        "que gostoso", "que gostosa", "que tesão", "que safada", "que linda",
        "que delicia", "que delícia", "sensacional", "fantastico", "fantástico",
        
        # Expressões casuais de interesse
        "me interessa", "tô afim", "to afim", "tô interessado", "to interessado",
        "quero ver", "quero conhecer", "quero saber", "conta mais", "me fala",
        "explica", "como é", "que tipo", "tem o que", "vem com o que"
    ]
    
    # Se tem palavras diretas de interesse, já retorna True (mais eficiente)
    if any(palavra in msg for palavra in palavras_interesse_diretas):
        logger.info(f"🎯 INTERESSE DETECTADO (palavras diretas) na mensagem: '{mensagem_usuario}' do usuário {user_id}")
        return True
    
    # Se não tem palavras diretas, usa IA para análise mais complexa
    prompt_deteccao = f"""
Analise se esta mensagem indica que a pessoa QUER COMPRAR algo, após ter visto uma tabela de produtos:

Mensagem: "{mensagem_usuario}"

A pessoa está interessada em comprar? Responda APENAS "SIM" ou "NÃO".

Exemplos de SIM:
- "quero" "interessado" "aquele ali" "esse daí" "esse lá" "aquele lá" "vou pegar" 
- "quanto custa" "como funciona" "legal" "gostei" "show" "top" "bacana" 
- "nossa" "que delícia" "adorei" "curti" "fechado" "bora" "vamos" 
- "pode ser" "beleza" "ok" "sim" "claro" "demais" "me interessa" "tô afim"
- Qualquer demonstração de interesse ou escolha
- Elogios sobre os produtos/conteúdos
- Perguntas sobre preço, funcionamento, pagamento

Exemplos de NÃO:
- "não quero" "não me interessa" "muito caro" "não tenho dinheiro" 
- "talvez depois" "vou pensar" "não gostei" "não posso" "sem condições"
- Conversas sobre outros assuntos não relacionados a compra
- Reclamações ou críticas negativas

Resposta:"""

    try:
        async with openai_semaphore:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_deteccao}],
                temperature=0.2,  # Ainda mais baixa para consistência
                max_tokens=5,     # Só precisa de "SIM" ou "NÃO"
            )
            
            resposta_ia = response.choices[0].message.content.strip().upper()
            
            # Verifica se é SIM (com verificações extras)
            if "SIM" in resposta_ia or "YES" in resposta_ia:
                logger.info(f"🤖 IA detectou INTERESSE na mensagem: '{mensagem_usuario}' do usuário {user_id} - Resposta IA: '{resposta_ia}'")
                return True
            else:
                logger.info(f"🤖 IA detectou SEM interesse na mensagem: '{mensagem_usuario}' do usuário {user_id} - Resposta IA: '{resposta_ia}'")
                return False
                
    except Exception as e:
        logger.error(f"❌ Erro na detecção inteligente de interesse: {e}")
        # Fallback MELHORADO: se der erro na IA, usa detecção simples melhorada
        palavras_fallback = [
            "quero", "interessado", "legal", "show", "top", "sim", "ok", "beleza", 
            "aquele", "esse", "ali", "lá", "gostei", "adorei", "nossa", "demais"
        ]
        resultado = any(palavra in msg for palavra in palavras_fallback)
        if resultado:
            logger.info(f"🔧 FALLBACK: Interesse detectado na mensagem: '{mensagem_usuario}' do usuário {user_id}")
        return resultado

# TAMBÉM adicione esta função de DEBUG (opcional):
async def debug_deteccao_interesse(mensagem_usuario, user_id):
    """Função para debug - mostra todo o processo de detecção"""
    logger.info(f"🔍 DEBUG: Analisando mensagem '{mensagem_usuario}' do usuário {user_id}")
    logger.info(f"🔍 DEBUG: Usuário viu tabela? {user_id in usuarios_viram_tabela}")
    
    if user_id in usuarios_viram_tabela:
        resultado = await detectar_interesse_inteligente(mensagem_usuario, user_id)
        logger.info(f"🔍 DEBUG: Resultado final: {resultado}")
        return resultado
    return False

def detectar_interesse_sem_pacote(mensagem_usuario, user_id):
    """
    FUNÇÃO OBSOLETA - mantida apenas para compatibilidade
    Use detectar_interesse_inteligente() ao invés desta
    """
    return False  # Desabilitada

def detectar_resposta_negativa(mensagem_usuario, user_id):
    """
    Detecta se usuário deu resposta negativa após ver a tabela
    """
    if user_id not in usuarios_viram_tabela:
        return False
    
    if user_id in usuarios_oferta_desconto:
        return False
    
    msg = mensagem_usuario.lower()
    
    palavras_negativas = [
        # ===== NEGAÇÃO DIRETA =====
        "não", "aff", "dps eu compro ta", "n quero agora", "nao", "não quero", "nao quero", "não tenho interesse", "nao tenho interesse",
        "não me interessa", "nao me interessa", "não gosto", "nao gosto", "não curto", "nao curto",
        "não quero não", "nao quero nao", "não mesmo", "nao mesmo", "jamais", "nunca",
        "de jeito nenhum", "nem pensar", "nem a pau", "nem ferrando", "sem chance",
        
        # ===== TEMPORAL (NÃO AGORA) =====
        "hoje não", "hoje nao", "agora não", "agora nao", "não hoje", "nao hoje",
        "não agora", "nao agora", "mais tarde", "depois", "outra hora", "outro dia",
        "amanhã", "semana que vem", "mês que vem", "próximo mês", "proximo mes",
        "ano que vem", "quando tiver tempo", "quando puder", "outro momento",
        "deixa pra depois", "deixa pra semana que vem", "talvez outro dia",
        
        # ===== FINANCEIRO =====
        "não tenho dinheiro", "nao tenho dinheiro", "tô sem dinheiro", "to sem dinheiro",
        "sem grana", "sem money", "duro", "liso", "quebrado", "sem condições", "sem condicoes",
        "muito caro", "caro demais", "tá caro", "ta caro", "salgado", "pesado", "puxado",
        "não cabe no bolso", "nao cabe no bolso", "fora do orçamento", "orcamento",
        "não posso", "nao posso", "não dá", "nao da", "não rola", "nao rola",
        "tô duro", "to duro", "tô sem", "to sem", "conta no vermelho", "sem bufunfa",
        "desempregado", "sem trabalho", "apertado", "difícil", "dificil", "complicado",
        
        # ===== HESITAÇÃO =====
        "vou pensar", "deixa eu pensar", "vou ver", "talvez", "quem sabe",
        "não sei", "nao sei", "em dúvida", "em duvida", "incerto", "indeciso",
        "meio que", "sei lá", "sei la", "não tenho certeza", "nao tenho certeza",
        "preciso analisar", "vou avaliar", "preciso decidir", "ainda não decidi",
        "ainda nao decidi", "tô pensando", "to pensando", "deixa eu ver",
        
        # ===== COMPARAÇÃO/PESQUISA =====
        "vou pesquisar", "vou comparar", "tem mais barato", "acho em outro lugar",
        "vou procurar", "tem concorrência", "concorrencia", "vou ver outros",
        "quero comparar preços", "precos", "tem similar", "conheco parecido",
        "vou dar uma olhada", "preciso pesquisar", "vou no google",
        
        # ===== DESINTERESSE TOTAL =====
        "não gostei", "nao gostei", "não curtiu", "nao curtiu", "não é pra mim", "nao e pra mim",
        "não combina", "nao combina", "não serve", "nao serve", "não rola mesmo", "nao rola mesmo",
        "desanimei", "perdi interesse", "mudei de ideia", "mudei de ideia", "desisti",
        "não quero mais", "nao quero mais", "não vale", "nao vale", "bobagem",
        "besteira", "furada", "enganação", "enganacao", "golpe", "não acredito", "nao acredito",
        
        # ===== CASUAL/INFORMAL =====
        "passa", "deixa pra lá", "deixa pra la", "esquece", "tanto faz", "whatever",
        "flw", "falou", "tchau", "bye", "xau", "até", "ate", "beleza então", "entao",
        "fica pra próxima", "fica pra proxima", "uma outra hora", "depois a gente vê", "ve",
        "valeu", "obrigado mas não", "obrigado mas nao", "vlw mas não", "vlw mas nao",
        
        # ===== SUSPENSE/DESCONFIANÇA =====
        "é furada", "e furada", "não confio", "nao confio", "parece golpe", "golpe",
        "muito suspeito", "desconfio", "parece fake", "fake", "enganação", "enganacao",
        "não acredito nisso", "nao acredito nisso", "mentira", "balela", "papo furado",
        "conversa fiada", "história mal contada", "historia mal contada", "pegadinha",
        
        # ===== COMPROMISSOS/OCUPAÇÃO =====
        "tô ocupado", "to ocupado", "sem tempo", "corrido", "cheio de coisa",
        "muito trabalho", "não tenho tempo", "nao tenho tempo", "agenda lotada",
        "comprometido", "não posso agora", "nao posso agora", "tenho compromisso",
        "tô viajando", "to viajando", "fora da cidade", "não tô em casa", "nao to em casa",
        
        # ===== VARIAÇÕES REGIONAIS/GÍRIAS =====
        "oxe não", "oxe nao", "eita não", "eita nao", "capaz", "que nada", "magina",
        "imagina", "tá doido", "ta doido", "tá maluco", "ta maluco", "viajou",
        "sonhando", "delirando", "pirou", "surtou", "endoidou", "tá bom não", "ta bom nao",
        
        # ===== EDUCADO MAS NEGATIVO =====
        "obrigado mas não", "obrigado mas nao", "agradeço mas não", "agradeco mas nao",
        "muito gentil mas não", "muito gentil mas nao", "fico grato mas não", "fico grato mas nao",
        "adorei a oferta mas não", "adorei a oferta mas nao", "linda proposta mas não",
        "linda proposta mas nao", "interessante mas não", "interessante mas nao",
        
        # ===== CURTO E GROSSO =====
        "nope", "nop", "negativo", "negative", "nada", "zero", "jamé", "nunca mais",
        "nem", "neca", "nenhum", "ninguém", "ninguem", "nada disso", "que isso",
        "para", "pare", "chega", "basta", "para com isso", "para de insistir"
    ]
    
    tem_negativa = any(palavra in msg for palavra in palavras_negativas)
    
    if tem_negativa:
        logger.info(f"❌ RESPOSTA NEGATIVA detectada: '{mensagem_usuario}' do usuário {user_id}")
        return True
    
    return False

def detectar_interesse_desconto(mensagem_usuario, user_id):
    """
    Detecta se usuário mostrou interesse na oferta de desconto de R$ 15
    """
    if user_id not in usuarios_oferta_desconto:
        return False
    
    msg = mensagem_usuario.lower()
    
    palavras_interesse_desconto = [
        # ===== CONFIRMAÇÃO DIRETA =====
        "sim", "yes", "quero", "aceito", "fechado", "vou querer", "eu quero", 
        "ok", "okay", "beleza", "claro", "óbvio", "obvio", "com certeza", "certeza",
        "pode ser", "tá bom", "ta bom", "tudo bem", "legal", "show", "top", "bacana",
        "perfeito", "ótimo", "otimo", "excelente", "maravilhoso", "adorei", "amei",
        
        # ===== CONCORDÂNCIA CASUAL =====
        "gostei", "curti", "adorei", "amei", "demais", "massa", "maneiro", "irado",
        "da hora", "sensacional", "incrível", "incrivel", "fantástico", "fantastico",
        "nossa", "nossa sim", "claro que sim", "com toda certeza", "sem dúvida", "sem duvida",
        "é isso aí", "e isso ai", "é isso mesmo", "e isso mesmo", "exato", "isso mesmo",
        
        # ===== INTERESSE ESPECÍFICO NO VALOR =====
        "15 reais", "de 15", "por 15", "r$ 15", "rs 15", "15,00", "quinze reais",
        "esse preço", "nesse valor", "assim eu pago", "assim rola", "assim dá", "assim da",
        "assim eu consigo", "assim eu compro", "nesse valor eu pego", "por esse preço",
        "15 tá bom", "15 ta bom", "15 eu pago", "15 beleza", "15 fechou", "15 ok",
        "vale os 15", "pelos 15", "nos 15", "com 15", "só 15", "so 15", "apenas 15",
        
        # ===== AJUDA/SOLIDARIEDADE =====
        "vou te ajudar", "quero ajudar", "pra te ajudar", "te ajudo", "por você", "por voce",
        "pra você", "pra voce", "uma força", "forcinha", "te dou uma força", "te dou uma forcinha",
        "solidariedade", "vou colaborar", "quero colaborar", "contribuir", "dar uma mão", "dar uma mao",
        "apoiar", "te apoio", "estou contigo", "to contigo", "vamos juntas", "juntos",
        
        # ===== URGÊNCIA/OPORTUNIDADE =====
        "aproveitar", "vou aproveitar", "quero aproveitar", "oportunidade", "não posso perder", "nao posso perder",
        "última chance", "ultima chance", "promoção", "promocao", "desconto", "oferta",
        "vale a pena", "compensa", "vantagem", "benefício", "beneficio", "economia",
        "barato assim", "preço bom", "preco bom", "em conta", "acessível", "acessivel",
        
        # ===== MUDANÇA DE OPINIÃO =====
        "mudou minha opinião", "mudou minha opiniao", "agora sim", "assim sim", "agora vai",
        "agora compro", "agora pago", "agora aceito", "agora quero", "dessa forma sim",
        "dessa forma eu quero", "assim eu aceito", "mudei de ideia", "mudei de ideia",
        "me convenceu", "me convenceste", "conseguiu", "vendeu", "fechou comigo",
        
        # ===== INTERESSE GERAL =====
        "me interessa", "interessante", "chamou atenção", "chamou atencao", "despertou interesse",
        "fiquei interessado", "fiquei interessada", "gostei da proposta", "boa proposta",
        "proposta interessante", "oferta boa", "oferta interessante", "me chamou atenção", "me chamou atencao",
        
        # ===== APROVAÇÃO ENTUSIASMADA =====
        "nossa que bom", "que legal", "que bacana", "que massa", "que show", "que top",
        "adorei isso", "curti demais", "gostei muito", "amei a ideia", "ideia boa",
        "pensou em tudo", "perfeito assim", "ideal", "combinou", "fechou", "bateu",
        
        # ===== DECISÃO RÁPIDA =====
        "rapidinho", "rápido", "rapido", "já", "ja", "agora", "imediatamente",
        "na hora", "sem pensar", "sem hesitar", "decidido", "decidiu", "convencido",
        "vendido", "comprado", "fechado comigo", "topa", "topei", "aceita", "aceitei",
        
        # ===== FINANCEIRO POSITIVO =====
        "cabe no bolso", "tenho os 15", "consigo os 15", "dá pra pagar", "da pra pagar",
        "posso pagar", "consigo pagar", "dá sim", "da sim", "rola sim", "beleza sim",
        "tranquilo", "de boa", "numa boa", "consigo", "dá", "da", "rola", "vai",
        
        # ===== TEMPORAL POSITIVO =====
        "agora mesmo", "hoje mesmo", "já pago", "ja pago", "pago agora", "agora então", "agora entao",
        "sem demora", "rapidão", "rapidao", "sem perder tempo", "vamos logo", "bora então", "bora entao",
        "não vou esperar", "nao vou esperar", "antes que acabe", "antes que termine",
        
        # ===== SOCIAL/EMOCIONAL =====
        "você merece", "voce merece", "coitadinha", "tadinha", "merecido", "justo",
        "é pouco", "e pouco", "baratinho", "fichinha", "mixaria", "troco", "trocado",
        "vale muito mais", "deveria ser mais caro", "tá barato", "ta barato", "preço justo", "preco justo",
        
        # ===== REGIONAL/GÍRIAS =====
        "bora", "bora lá", "bora la", "partiu", "é nóis", "e nois", "fechou comigo",
        "tamo junto", "cola aí", "cola ai", "vamu que vamu", "bora bill", "suave",
        "de lei", "firmeza", "massa", "irado", "sinistro", "brabo", "top demais",
        
        # ===== CONFIRMAÇÃO MÚLTIPLA =====
        "sim sim", "quero sim", "aceito sim", "claro que sim", "obvio que sim", "é claro", "e claro",
        "pode mandar", "manda aí", "manda ai", "pode enviar", "envia aí", "envia ai",
        "vamos fazer", "vamos fechar", "fecha comigo", "tá fechado", "ta fechado", "combinado",
        
        # ===== EXPRESSÕES DE ALÍVIO =====
        "ainda bem", "que bom", "melhor assim", "assim fica bom", "agora sim fica bom",
        "respirei", "ufa", "que alívio", "que alivio", "consegui", "deu certo", "deu bom",
        "perfeito então", "perfeito entao", "ideal então", "ideal entao", "ótimo então", "otimo entao",
        
        # ===== COMPARAÇÃO POSITIVA =====
        "melhor que", "muito melhor", "bem melhor", "mais barato que", "mais em conta",
        "compensa mais", "vale mais", "saiu melhor", "ficou melhor", "assim fica melhor",
        "prefiro assim", "assim é melhor", "assim e melhor", "gosto mais assim",
        
        # ===== CONFIANÇA =====
        "confio", "acredito", "pode contar", "tô dentro", "to dentro", "embarco",
        "vou nessa", "topo", "entra", "bora nessa", "vamu", "partiu então", "partiu entao",
        "vai que vai", "bora que bora", "fechou então", "fechou entao", "combinado então", "combinado entao"
    ]
    
    tem_interesse = any(palavra in msg for palavra in palavras_interesse_desconto)
    
    if tem_interesse:
        logger.info(f"💰 INTERESSE NO DESCONTO detectado: '{mensagem_usuario}' do usuário {user_id}")
        return True
    
    return False

async def enviar_sequencia_desconto(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Envia sequência completa de desconto: áudio + vídeo + vídeo + áudio final
    """
    try:
        logger.info(f"🎯 Iniciando sequência de desconto para usuário {user_id}")
        
        usuarios_oferta_desconto.add(user_id)
        usuarios_rejeitaram_inicial.add(user_id)
        
        # PASSO 1: Primeiro áudio
        await asyncio.sleep(random.uniform(2, 4))
        
        if os.path.exists(DESCONTO_AUDIO1_PATH):
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id,
                    action=ChatAction.RECORD_VOICE
                )
                await asyncio.sleep(random.uniform(1, 2))
                
                with open(DESCONTO_AUDIO1_PATH, 'rb') as voice_file:
                    await update.message.reply_voice(voice=voice_file)
                logger.info(f"🎵 Primeiro áudio de desconto enviado para {user_id}")
                
            except Exception as e:
                logger.error(f"Erro ao enviar primeiro áudio: {e}")
                if "Voice_messages_forbidden" in str(e):
                    await update.message.reply_text("peraí amor, deixa eu te convencer ||| tenho uma proposta especial pra vc")
        else:
            await update.message.reply_text("peraí amor, deixa eu te convencer ||| tenho uma proposta especial pra vc")
        
        # PASSO 2: Primeiro vídeo
        await asyncio.sleep(random.uniform(3, 5))
        
        if os.path.exists(DESCONTO_VIDEO1_PATH):
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id,
                    action=ChatAction.UPLOAD_VIDEO
                )
                await asyncio.sleep(random.uniform(1, 3))
                
                with open(DESCONTO_VIDEO1_PATH, 'rb') as video_file:
                    await update.message.reply_video(video=video_file)
                logger.info(f"🎬 Primeiro vídeo de desconto enviado para {user_id}")
                
            except Exception as e:
                logger.error(f"Erro ao enviar primeiro vídeo: {e}")
        
        # PASSO 3: Segundo vídeo  
        await asyncio.sleep(random.uniform(3, 5))
        
        if os.path.exists(DESCONTO_VIDEO2_PATH):
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id,
                    action=ChatAction.UPLOAD_VIDEO
                )
                await asyncio.sleep(random.uniform(1, 3))
                
                with open(DESCONTO_VIDEO2_PATH, 'rb') as video_file:
                    await update.message.reply_video(video=video_file)
                logger.info(f"🎬 Segundo vídeo de desconto enviado para {user_id}")
                
            except Exception as e:
                logger.error(f"Erro ao enviar segundo vídeo: {e}")
        
        # PASSO 4: Áudio final com oferta
        await asyncio.sleep(random.uniform(4, 6))
        
        if os.path.exists(DESCONTO_AUDIO2_PATH):
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id,
                    action=ChatAction.RECORD_VOICE
                )
                await asyncio.sleep(random.uniform(2, 3))
                
                with open(DESCONTO_AUDIO2_PATH, 'rb') as voice_file:
                    await update.message.reply_voice(voice=voice_file)
                logger.info(f"🎵 Áudio final de desconto enviado para {user_id}")
                
            except Exception as e:
                logger.error(f"Erro ao enviar áudio final: {e}")
                if "Voice_messages_forbidden" in str(e):
                    await update.message.reply_text("olha só amor ||| vou deixar o pacote namoradinha por apenas 15 reais pra te ajudar")
                    await asyncio.sleep(random.uniform(2, 3))
                    await update.message.reply_text("é só pra me dar uma forcinha bb ||| você tem interesse?")
        else:
            await update.message.reply_text("olha só amor ||| vou deixar o pacote namoradinha por apenas 15 reais pra te ajudar")
            await asyncio.sleep(random.uniform(2, 3))
            await update.message.reply_text("é só pra me dar uma forcinha bb ||| você tem interesse?")
        
        logger.info(f"✅ Sequência completa de desconto enviada para usuário {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro na sequência de desconto para {user_id}: {e}")

async def gerar_pix_desconto(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Gera PIX de EXATAMENTE R$ 15,00 - VERSÃO CORRIGIDA UTMIFY
    """
    try:
        import requests
        import json
        
        from pagamento import (
            pagamentos_pendentes, 
            usuario_pagamento, 
            api_url, 
            headers, 
            WEBHOOK_URL
        )
        
        logger.info(f"💰 Gerando PIX de desconto R$ 15,00 para usuário {user_id}")
        
        # Cancela pagamento anterior se existir
        if user_id in usuario_pagamento:
            old_id = usuario_pagamento[user_id]
            if old_id in pagamentos_pendentes:
                del pagamentos_pendentes[old_id]
                logger.info(f"🗑️ Removido pagamento anterior: {old_id}")
            del usuario_pagamento[user_id]
        
        # Payload para PIX de R$ 15,00 (1500 centavos)
        payload = {
            "value": 1500,  # EXATAMENTE R$ 15,00
            "webhook_url": f"{WEBHOOK_URL}/webhook"
        }
        
        logger.info(f"📡 Criando PIX DESCONTO - User: {user_id}, Valor: R$ 15,00 (1500 centavos)")
        
        # Faz request para PushinPay
        response = requests.post(
            f"{api_url}/api/pix/cashIn",
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        
        logger.info(f"📊 Status da API: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            codigo_pix = data.get('qr_code')
            transaction_id = data.get('id')
            
            if codigo_pix and transaction_id:
                # Salva informações do pagamento ESPECIAL
                pagamentos_pendentes[transaction_id] = {
                    'user_id': user_id,
                    'pacote': "3",  # Entrega pacote NAMORADINHA
                    'valor': 1500,  # Valor REAL pago
                    'desconto': True  # Flag para identificar desconto
                }
                usuario_pagamento[user_id] = transaction_id
                
                logger.info(f"💾 Pagamento DESCONTO salvo - ID: {transaction_id}")
                logger.info(f"💾 User: {user_id}, Valor REAL: R$ 15,00")
                
                # Envia mensagens do PIX
                await update.message.reply_text("ta bom amor vou te enviar o pix aqui em baixo, é pix copia e cola ta bom")
                await asyncio.sleep(2)
                
                await update.message.reply_text(f"🔄 PIX Copia e Cola - R$ 15,00:\n\n`{codigo_pix}`", parse_mode='Markdown')
                await asyncio.sleep(1)
                
                await update.message.reply_text("15 reais só pra me ajudar bb ❤️ ||| quando pagar te mando o acesso da namoradinha")
                
                # UTMIFY tracking CORRIGIDO - envia valor R$ 15
                try:
                    from utmify_tracker import enviar_pix_desconto_gerado
                    utmify_result = enviar_pix_desconto_gerado(user_id, 1500)  # 1500 centavos = R$ 15
                    if utmify_result:
                        logger.info(f"📊 UTMIFY: PIX desconto R$ 15 trackado - User: {user_id}")
                    else:
                        logger.warning(f"⚠️ UTMIFY: Falha ao trackear PIX desconto - User: {user_id}")
                except Exception as e:
                    logger.error(f"❌ UTMIFY: Erro ao trackear PIX desconto: {e}")
                
                logger.info(f"✅ PIX de R$ 15,00 gerado com sucesso para usuário {user_id}")
                return True
                
            else:
                logger.error("❌ Transaction ID ou QR Code não encontrado")
                return False
        else:
            logger.error(f"❌ Erro na API: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar PIX de desconto: {e}")
        return False

# ===== VERIFICAÇÃO DE DEBUG =====

# ADICIONE esta função para debug (opcional):
def debug_pix_desconto():
    """Função para debugar se o PIX de desconto está funcionando"""
    print("🔍 DEBUG - PIX de Desconto:")
    print("✅ Valor: R$ 15,00 (1500 centavos)")
    print("✅ Entrega: Pacote Namoradinha (mais caro)")
    print("✅ Webhook configurado")
    print("✅ UTMIFY tracking ativo")
    
    # Verifica se as importações estão funcionando
    try:
        from pagamento import pagamentos_pendentes, usuario_pagamento, api_url, headers, WEBHOOK_URL
        print("✅ Imports do pagamento.py funcionando")
        print(f"🔗 API URL: {api_url}")
        print(f"🔗 Webhook: {WEBHOOK_URL}")
    except Exception as e:
        print(f"❌ Erro nos imports: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipula mensagens recebidas do usuário"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # RASTREAR ATIVIDADE DO USUÁRIO
    track_user_activity(user_id)
    
    # Para o remarketing quando usuário responde
    stop_remarketing(user_id)
    
    user_id_str = str(user_id)
    
    # Inicializa histórico de conversa para um novo usuário
    if user_id_str not in conversation_history:
        conversation_history[user_id_str] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    
    # 1. PRIMEIRO: Verifica se usuário escolheu um pacote específico
    # NOVA VERIFICAÇÃO: SÓ detecta pacotes se usuário já viu a tabela
    pacote_escolhido = None
    if user_id in usuarios_viram_tabela:
        # Só detecta pacotes se já viu a tabela
        pacote_escolhido = detectar_pacote_escolhido(user_message)
        if pacote_escolhido:
            logger.info(f"🎯 Pacote detectado: {pacote_escolhido} para usuário {user_id} (já viu tabela)")
    else:
        # Se não viu tabela, não detecta pacotes
        logger.info(f"🚫 Usuário {user_id} não viu tabela ainda - não detectando pacotes")
    
    if pacote_escolhido:
        # Verifica se é o primeiro PIX deste usuário
        is_primeiro_pix = user_id not in usuarios_primeiro_pix
        
        # Cria PIX para o pacote escolhido
        dados_pix = criar_pix_pagamento(user_id, pacote_escolhido)
        
        if dados_pix:
            # NOVO: Envia evento PIX gerado para UTMIFY
            try:
                utmify_result = enviar_pix_gerado(user_id, pacote_escolhido)
                if utmify_result:
                    logger.info(f"📊 UTMIFY: PIX gerado trackado - User: {user_id}, Pacote: {pacote_escolhido}")
                else:
                    logger.warning(f"⚠️ UTMIFY: Falha ao trackear PIX gerado - User: {user_id}")
            except Exception as e:
                logger.error(f"❌ UTMIFY: Erro ao trackear PIX gerado: {e}")
            
            # Adiciona usuário à lista de quem já gerou PIX
            if is_primeiro_pix:
                usuarios_primeiro_pix.add(user_id)
            
            # Formata mensagens
            mensagem, codigo_pix = formatar_resposta_pix(dados_pix)
            
            # Envia mensagem
            await update.message.reply_text(mensagem)
            await asyncio.sleep(2)
            
            # Envia código PIX
            await update.message.reply_text(f"🔄 PIX Copia e Cola:\n\n`{codigo_pix}`", parse_mode='Markdown')
            await asyncio.sleep(1)
            
            # Instrução final
            await update.message.reply_text("copie o código acima e cole no seu app do banco\n\nquando pagar te mando o acesso automaticamente bb ❤️")
            
            # NOVO: Envia áudio de comprovante APENAS no primeiro PIX
            if is_primeiro_pix:
                await asyncio.sleep(2)
                
                # Verifica se o arquivo de áudio existe
                if os.path.exists(COMPROVANTE_AUDIO_PATH):
                    try:
                        # Simula gravação de áudio
                        await context.bot.send_chat_action(
                            chat_id=update.effective_message.chat_id, 
                            action=ChatAction.RECORD_VOICE
                        )
                        await asyncio.sleep(random.uniform(1, 2))
                        
                        # Envia áudio de comprovante
                        with open(COMPROVANTE_AUDIO_PATH, 'rb') as voice_file:
                            await update.message.reply_voice(voice=voice_file)
                        
                        logger.info(f"🎵 Áudio de comprovante enviado para usuário {user_id} (primeiro PIX)")
                        
                    except Exception as e:
                        logger.error(f"Erro ao enviar áudio de comprovante: {e}")
                        # Se der erro com áudio, envia mensagem de texto
                        if "Voice_messages_forbidden" in str(e):
                            await update.message.reply_text("lembre de me mandar o comprovante quando pagar bb")
                        else:
                            await update.message.reply_text("qualquer coisa me manda o comprovante depois amor")
                else:
                    logger.warning(f"Áudio de comprovante não encontrado: {COMPROVANTE_AUDIO_PATH}")
                    await update.message.reply_text("me manda o comprovante quando pagar bb")
            else:
                logger.info(f"💰 PIX adicional gerado para usuário {user_id} - Áudio não enviado (não é o primeiro)")
            
            logger.info(f"💰 PIX gerado para usuário {user_id} - Pacote: {pacote_escolhido} - Primeiro PIX: {is_primeiro_pix}")
            
            # Inicia remarketing e sai
            start_remarketing(user_id)
            return
        else:
            await update.message.reply_text("nossa deu erro pra gerar o pix amor ||| tenta denovo")
            start_remarketing(user_id)
            return
    
    # 2. SEGUNDO: Verifica se usuário está pedindo a TABELA
    if detectar_pedido_tabela(user_message):
        # Cliente quer ver a tabela - enviar imediatamente
        respostas_enviar_tabela = [
            "claro amor, vou mandar denovo ||| ***ENVIAR_TABELA***",
            "claro bb, ai está a tabela ||| ***ENVIAR_TABELA***",
            "claro mozão, olha só ||| ***ENVIAR_TABELA***",
            "pode deixar amor ||| ***ENVIAR_TABELA***",
            "claro lindinho ||| ***ENVIAR_TABELA***"
        ]
        
        resposta = random.choice(respostas_enviar_tabela)
        
        # Processa a resposta (vai enviar tabela automaticamente)
        if "|||" in resposta:
            first_part, second_part = [part.strip() for part in resposta.split("|||")]
            
            # Primeira mensagem
            await asyncio.sleep(random.uniform(1, 2))
            await send_typing_action(update, context)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            await update.message.reply_text(first_part)
            
            # Verifica se tem marcador para enviar tabela
            if "***ENVIAR_TABELA***" in second_part:
                # Delay antes de enviar a tabela
                await asyncio.sleep(random.uniform(2, 3))
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id, 
                    action=ChatAction.UPLOAD_PHOTO
                )
                await asyncio.sleep(random.uniform(1, 2))
                
                # Enviar tabela de preços
                if os.path.exists(PRICE_TABLE_PATH):
                    try:
                        with open(PRICE_TABLE_PATH, 'rb') as photo_file:
                            await update.message.reply_photo(
                                photo=photo_file,
                                caption="qual pacotinho voce vai querer amor?"
                            )
                        
                        # Marca que usuário viu a tabela
                        usuarios_viram_tabela.add(user_id)
                        
                        logger.info(f"📋 Tabela reenviada para o usuário {user_id}")
                    except Exception as e:
                        logger.error(f"Erro ao reenviar tabela: {e}")
                        await update.message.reply_text("pera q vou te mandar os valores")
                else:
                    logger.warning(f"Tabela de preços não encontrada: {PRICE_TABLE_PATH}")
                    await update.message.reply_text("os valores estão bem acessíveis amor")
        
        # Inicia remarketing e sai
        start_remarketing(user_id)
        return
    
    # 3. TERCEIRO: Verifica se usuário está pedindo PRÉVIA
    if detectar_pedido_previa(user_message):
        # Cliente quer ver prévia - enviar imediatamente
        respostas_enviar_previa = [
            "espera aí vou mandar uma previazinha pra vc ||| ***ENVIAR_PREVIA***",
            "claro amor, vou te mostrar um pouquinho ||| ***ENVIAR_PREVIA***",
            "pode deixar bb, olha só ||| ***ENVIAR_PREVIA***",
            "claro mozão, só pra te deixar com água na boca ||| ***ENVIAR_PREVIA***",
            "vou te mandar algo gostoso ||| ***ENVIAR_PREVIA***"
        ]
        
        resposta = random.choice(respostas_enviar_previa)
        
        # Processa a resposta (vai enviar prévia automaticamente)
        if "|||" in resposta:
            first_part, second_part = [part.strip() for part in resposta.split("|||")]
            
            # Primeira mensagem
            await asyncio.sleep(random.uniform(1, 2))
            await send_typing_action(update, context)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            await update.message.reply_text(first_part)
            
            # Verifica se tem marcador para enviar prévia
            if "***ENVIAR_PREVIA***" in second_part:
                # Delay antes de enviar o vídeo de prévia
                await asyncio.sleep(random.uniform(2, 4))
                await context.bot.send_chat_action(
                    chat_id=update.effective_message.chat_id, 
                    action=ChatAction.UPLOAD_VIDEO
                )
                await asyncio.sleep(random.uniform(1, 2))
                
                # Enviar vídeo de prévia
                if os.path.exists(PREVIEW_VIDEO_PATH):
                    try:
                        with open(PREVIEW_VIDEO_PATH, 'rb') as video_file:
                            await update.message.reply_video(
                                video=video_file,
                                caption="so pra te deixar no gostinho kk"
                            )
                        logger.info(f"🎬 Prévia enviada para o usuário {user_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar prévia: {e}")
                        await update.message.reply_text("nossa deu problema no video mas garanto que vai amar")
                else:
                    logger.warning(f"Vídeo de prévia não encontrado: {PREVIEW_VIDEO_PATH}")
                    await update.message.reply_text("não tenho prévias mas garanto que você vai amar os videos")
        
        # Inicia remarketing e sai
        start_remarketing(user_id)
        return
    
    # X. VERIFICAÇÃO DE RESPOSTA NEGATIVA (NOVO)
    if detectar_resposta_negativa(user_message, user_id):
        await enviar_sequencia_desconto(update, context, user_id)
        start_remarketing(user_id)
        return

    # Y. VERIFICAÇÃO DE INTERESSE NO DESCONTO (NOVO)  
    if detectar_interesse_desconto(user_message, user_id):
        sucesso = await gerar_pix_desconto(update, context, user_id)
        if sucesso:
            start_remarketing(user_id)
            return
        else:
            await update.message.reply_text("deu erro no pix amor ||| tenta falar denovo")
            start_remarketing(user_id)
            return
    
    # 4. QUARTO: Verifica se usuário mostrou interesse mas não especificou pacote (VERSÃO INTELIGENTE)
    interesse_detectado = await detectar_interesse_inteligente(user_message, user_id)
    if interesse_detectado:
        # Pergunta qual pacote ele quer
        respostas_qual_pacote = [
            "qual pacote amor? gostosinha, grupo vip ou namoradinha?",
            "qual você quer bb? gostosinha, vip ou namoradinha?", 
            "me fala qual mozão? gostosinha, grupo vip ou namoradinha?",
            "qual vai ser amor? gostosinha, vip ou namoradinha?",
            "escolhe aí bb? gostosinha, grupo vip ou namoradinha?"
        ]
        
        resposta = random.choice(respostas_qual_pacote)
        
        # Delay natural
        await asyncio.sleep(random.uniform(1, 2))
        await send_typing_action(update, context)
        await asyncio.sleep(random.uniform(1.5, 2.5))
        
        await update.message.reply_text(resposta)
        
        logger.info(f"❓ Pergunta sobre qual pacote enviada para usuário {user_id} (IA detectou interesse)")
        
        # Inicia remarketing e sai
        start_remarketing(user_id)
        return
    
    # 5. QUINTO: Processamento normal com IA (se não detectou nada específico acima)
    
    # Delay mais natural antes de começar a "digitar"
    await asyncio.sleep(random.uniform(0.5, 2.0))
    
    # Mostra "digitando..." enquanto processa
    await send_typing_action(update, context)
    
    # Obtém resposta da AI
    response_text = await get_ai_response(user_message, user_id)
    
    # Simula tempo de digitação baseado no tamanho da mensagem
    typing_time = random.uniform(1.5, 3.5)
    await asyncio.sleep(typing_time)
    
    # Verifica se precisa enviar vídeo de prévia (da IA)
    if "***ENVIAR_PREVIA***" in response_text:
        # Remove o marcador da resposta
        response_text = response_text.replace("***ENVIAR_PREVIA***", "").strip()
        
        # Envia a mensagem normal primeiro (se houver)
        if response_text and "|||" in response_text:
            parts = [part.strip() for part in response_text.split("|||")]
            for i, part in enumerate(parts):
                if part:
                    await update.message.reply_text(part)
                    if i < len(parts) - 1:  # Se não for a última parte
                        await asyncio.sleep(random.uniform(2, 4))
                        await send_typing_action(update, context)
                        await asyncio.sleep(random.uniform(1, 2))
        elif response_text:
            await update.message.reply_text(response_text)
        
        # Delay antes de enviar o vídeo de prévia
        await asyncio.sleep(random.uniform(2, 4))
        await context.bot.send_chat_action(
            chat_id=update.effective_message.chat_id, 
            action=ChatAction.UPLOAD_VIDEO
        )
        await asyncio.sleep(random.uniform(1, 2))
        
        # Enviar vídeo de prévia
        if os.path.exists(PREVIEW_VIDEO_PATH):
            try:
                with open(PREVIEW_VIDEO_PATH, 'rb') as video_file:
                    await update.message.reply_video(
                        video=video_file,
                        caption="so pra te deixar no gostinho kk"
                    )
                logger.info(f"Vídeo de prévia enviado para o usuário {user_id}")
            except Exception as e:
                logger.error(f"Erro ao enviar vídeo de prévia: {e}")
                await update.message.reply_text("nossa deu problema no video mas garanto que vai amar")
        else:
            logger.warning(f"Vídeo de prévia não encontrado: {PREVIEW_VIDEO_PATH}")
            await update.message.reply_text("não tenho prévias mas garanto que você vai amar os videos")
    
    # Verifica se precisa enviar áudio de explicação (da IA)
    elif "***AUDIO_EXPLICACAO***" in response_text:
        # Remove o marcador da resposta
        response_text = response_text.replace("***AUDIO_EXPLICACAO***", "").strip()
        
        # Envia a mensagem normal primeiro (se houver)
        if response_text and "|||" in response_text:
            parts = [part.strip() for part in response_text.split("|||")]
            for i, part in enumerate(parts):
                if part:
                    await update.message.reply_text(part)
                    if i < len(parts) - 1:  # Se não for a última parte
                        await asyncio.sleep(random.uniform(2, 4))
                        await send_typing_action(update, context)
                        await asyncio.sleep(random.uniform(1, 2))
        elif response_text:
            await update.message.reply_text(response_text)
        
        # Delay antes de enviar o áudio de explicação
        await asyncio.sleep(random.uniform(2, 4))
        await context.bot.send_chat_action(
            chat_id=update.effective_message.chat_id, 
            action=ChatAction.RECORD_VOICE
        )
        await asyncio.sleep(random.uniform(2, 3))
        
        # Enviar áudio de explicação
        if os.path.exists(EXPLICACAO_AUDIO_PATH):
            try:
                with open(EXPLICACAO_AUDIO_PATH, 'rb') as voice_file:
                    await update.message.reply_voice(
                        voice=voice_file
                    )
                logger.info(f"Áudio de explicação enviado para o usuário {user_id}")
            except Exception as e:
                logger.error(f"Erro ao enviar áudio de explicação: {e}")
                # Verificar se é erro de mensagens de voz bloqueadas
                if "Voice_messages_forbidden" in str(e):
                    await update.message.reply_text("tenho videos bem safadinhos e fotos bem gostosas amor")
                else:
                    await update.message.reply_text("tenho uns conteúdos bem safadinhos pra vc")
        else:
            logger.warning(f"Áudio de explicação não encontrado: {EXPLICACAO_AUDIO_PATH}")
            await update.message.reply_text("tenho videos e fotos bem safadinhos mozao")
    
    # Verifica se precisa enviar tabela de preços (da IA)
    elif "***ENVIAR_TABELA***" in response_text:
        # Remove o marcador da resposta
        response_text = response_text.replace("***ENVIAR_TABELA***", "").strip()
        
        # Envia a mensagem normal primeiro (se houver)
        if response_text and "|||" in response_text:
            parts = [part.strip() for part in response_text.split("|||")]
            for i, part in enumerate(parts):
                if part:
                    await update.message.reply_text(part)
                    if i < len(parts) - 1:  # Se não for a última parte
                        await asyncio.sleep(random.uniform(2, 4))
                        await send_typing_action(update, context)
                        await asyncio.sleep(random.uniform(1, 2))
        elif response_text:
            await update.message.reply_text(response_text)
        
        # Delay antes de enviar a tabela
        await asyncio.sleep(random.uniform(2, 3))
        await context.bot.send_chat_action(
            chat_id=update.effective_message.chat_id, 
            action=ChatAction.UPLOAD_PHOTO
        )
        await asyncio.sleep(random.uniform(1, 2))
        
        # Enviar tabela de preços
        if os.path.exists(PRICE_TABLE_PATH):
            try:
                with open(PRICE_TABLE_PATH, 'rb') as photo_file:
                    await update.message.reply_photo(
                        photo=photo_file,
                        caption="qual pacotinho voce vai querer amor?"
                    )
                
                # Marca que usuário viu a tabela
                usuarios_viram_tabela.add(user_id)
                
                logger.info(f"Tabela de preços enviada para o usuário {user_id}")
            except Exception as e:
                logger.error(f"Erro ao enviar tabela: {e}")
                await update.message.reply_text("pera q vou te mandar os valores")
        else:
            logger.warning(f"Tabela de preços não encontrada: {PRICE_TABLE_PATH}")
            await update.message.reply_text("os valores estão bem acessíveis amor")
    
    # Verifica se a resposta contém o separador normal (2 partes)
    elif "|||" in response_text:
        # Divide a resposta em duas mensagens
        first_message, second_message = [msg.strip() for msg in response_text.split("|||", 1)]
        
        # Envia a primeira mensagem
        await update.message.reply_text(first_message)
        
        # Delay mais variável e natural entre mensagens
        pause_time = random.uniform(3, 7)
        await asyncio.sleep(pause_time)
        
        # Mostra "digitando..." novamente para a segunda mensagem
        await send_typing_action(update, context)
        
        # Tempo de digitação da segunda mensagem
        typing_time_2 = random.uniform(1, 3)
        await asyncio.sleep(typing_time_2)
        
        # Envia a segunda mensagem
        await update.message.reply_text(second_message)
    else:
        # Se não tem separador, envia a mensagem completa
        await update.message.reply_text(response_text)
    
    # Inicia remarketing após resposta da IA
    start_remarketing(user_id)

async def post_init(application):
    """Função chamada após inicialização do bot para startar o remarketing worker"""
    # Carrega métricas salvas
    load_metrics()
    
    # Inicia worker de remarketing OTIMIZADO
    asyncio.create_task(remarketing_worker(application))
    logger.info("Sistema de remarketing infinito OTIMIZADO ativo!")
    
    # Inicia dashboard web em thread separada
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    logger.info("Dashboard OTIMIZADA iniciada em http://localhost:5000")

# Variável global para acessar o application
application = None

def main() -> None:
    """Inicia o bot"""
    global application
    
    # Criar o aplicativo
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))

    # Manipulador de mensagens de voz
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    # Manipulador de mensagens não-comando
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Configurar post_init para startar o remarketing worker e dashboard
    application.post_init = post_init
    
    # NOVO: Configura sistema de pagamento PIX
    definir_callback_pagamento(quando_pagamento_confirmado)
    iniciar_servidor_webhook()
    
    logger.info("Bot OTIMIZADO iniciando...")
    logger.info("Dashboard estará disponível em: http://localhost:5000")
    logger.info("💰 Sistema PIX PushinPay ativo!")
    logger.info("🎯 Webhook PIX: porta 5001")

    # Iniciar o bot
    application.run_polling()

if __name__ == "__main__":
    main()