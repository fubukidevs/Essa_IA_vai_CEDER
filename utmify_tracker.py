import requests
import json
import logging
import random
import string
import time
import uuid
from datetime import datetime, timedelta
import threading

# ===== CONFIGURAÇÕES UTMIFY =====
UTMIFY_API_URL = "https://api.utmify.com.br/api-credentials/orders"
UTMIFY_API_TOKEN = "926FD9p3iW4QiiTz3yL1UjkUVetSXnlr9YlM"  # Substitua pelo seu token real
PLATFORM_NAME = "TelegramBot"               # Nome da sua plataforma
# ===================================

logger = logging.getLogger(__name__)

# Cache para evitar envios duplicados
vendas_enviadas = set()
lock = threading.Lock()

# Listas para geração de dados fictícios realistas
NOMES_MASCULINOS = [
    "João", "Pedro", "Lucas", "Gabriel", "Rafael", "Bruno", "André", "Carlos", 
    "Felipe", "Mateus", "Diego", "Rodrigo", "Leonardo", "Fernando", "Guilherme",
    "Ricardo", "Marcelo", "Thiago", "Alexandre", "Daniel", "Eduardo", "Fábio",
    "Gustavo", "Henrique", "Igor", "Juliano", "Leandro", "Marcos", "Nicolas",
    "Otávio", "Paulo", "Renato", "Samuel", "Vinícius", "William", "Anderson",
    "Caio", "Danilo", "Emerson", "Francisco", "Gustavo", "Heitor", "Ivan"
]

NOMES_FEMININOS = [
    "Ana", "Maria", "Fernanda", "Juliana", "Camila", "Beatriz", "Carla", "Débora",
    "Erika", "Fabiana", "Giovana", "Helena", "Isabela", "Jéssica", "Karen",
    "Larissa", "Mariana", "Natália", "Olívia", "Patrícia", "Queila", "Roberta",
    "Sabrina", "Tatiana", "Úrsula", "Vanessa", "Wanda", "Ximena", "Yasmin",
    "Zélia", "Amanda", "Bruna", "Carolina", "Daniela", "Eliane", "Flávia"
]

SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves",
    "Pereira", "Lima", "Gomes", "Costa", "Ribeiro", "Martins", "Carvalho",
    "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa", "Rocha",
    "Dias", "Monteiro", "Cardoso", "Reis", "Araújo", "Cavalcanti", "Nascimento",
    "Freitas", "Correia", "Miranda", "Teixeira", "Moreira", "Azevedo", "Campos",
    "Mendes", "Ramos", "Pinto", "Nunes", "Moura", "Castro", "Neves", "Pires"
]

DOMINIOS_EMAIL = [
    "gmail.com", "hotmail.com", "yahoo.com.br", "outlook.com", "uol.com.br",
    "terra.com.br", "bol.com.br", "ig.com.br", "globo.com", "r7.com",
    "live.com", "msn.com", "oi.com.br", "ibest.com.br", "zipmail.com.br"
]

# DDDs brasileiros realistas
DDDS_BRASIL = [
    "11", "12", "13", "14", "15", "16", "17", "18", "19",  # São Paulo
    "21", "22", "24",  # Rio de Janeiro
    "27", "28",  # Espírito Santo
    "31", "32", "33", "34", "35", "37", "38",  # Minas Gerais
    "41", "42", "43", "44", "45", "46",  # Paraná
    "47", "48", "49",  # Santa Catarina
    "51", "53", "54", "55",  # Rio Grande do Sul
    "61",  # Distrito Federal
    "62", "64",  # Goiás
    "63",  # Tocantins
    "65", "66",  # Mato Grosso
    "67",  # Mato Grosso do Sul
    "68",  # Acre
    "69",  # Rondônia
    "71", "73", "74", "75", "77",  # Bahia
    "79",  # Sergipe
    "81", "87",  # Pernambuco
    "82",  # Alagoas
    "83",  # Paraíba
    "84",  # Rio Grande do Norte
    "85", "88",  # Ceará
    "86", "89",  # Piauí
    "91", "93", "94",  # Pará
    "92", "97",  # Amazonas
    "95",  # Roraima
    "96",  # Amapá
    "98", "99"   # Maranhão
]

# Parâmetros UTM fictícios realistas
UTM_SOURCES = ["FB", "IG", "YT", "TT", "TW", "GO", "DIRECT", "ORGANIC"]
UTM_MEDIUMS = [
    "ABO|1273612873681723", "CONJUNTO_1|498046723566488", "TRAFEGO_PAGO|123456789",
    "STORY_ADS|987654321", "REELS_ADS|456789123", "VIDEO_ADS|789123456"
]
UTM_CAMPAIGNS = [
    "Vendas 2024|126351623512736523", "Black_Friday|887766554433221",
    "Natal_2024|998877665544332", "Promo_Janeiro|112233445566778"
]
UTM_CONTENTS = [
    "VIDEO_01|2412937293769713", "CRIATIVO_02|1357924680135792",
    "IMAGEM_03|8642097531864209", "CARROSSEL_04|9753186420975318"
]
UTM_TERMS = [
    "Instagram_Reels", "Instagram_Feed", "Facebook_Feed", "Instagram_Stories",
    "YouTube_Videos", "TikTok_FYP", "Google_Search", "Facebook_Stories"
]

def gerar_nome_completo():
    """Gera um nome completo brasileiro realista"""
    genero = random.choice(["M", "F"])
    
    if genero == "M":
        primeiro_nome = random.choice(NOMES_MASCULINOS)
    else:
        primeiro_nome = random.choice(NOMES_FEMININOS)
    
    # 70% chance de ter nome do meio
    if random.random() < 0.7:
        if genero == "M":
            nome_meio = random.choice(NOMES_MASCULINOS + ["dos", "de", "da"])
        else:
            nome_meio = random.choice(NOMES_FEMININOS + ["dos", "de", "da"])
        sobrenome = random.choice(SOBRENOMES)
        return f"{primeiro_nome} {nome_meio} {sobrenome}"
    else:
        sobrenome = random.choice(SOBRENOMES)
        return f"{primeiro_nome} {sobrenome}"

def gerar_email_ficticio(nome):
    """Gera um email fictício baseado no nome"""
    nome_limpo = nome.lower()
    nome_limpo = nome_limpo.replace(" ", "").replace("ã", "a").replace("ç", "c")
    nome_limpo = nome_limpo.replace("á", "a").replace("é", "e").replace("í", "i")
    nome_limpo = nome_limpo.replace("ó", "o").replace("ú", "u").replace("â", "a")
    nome_limpo = nome_limpo.replace("ê", "e").replace("ô", "o").replace("ü", "u")
    
    # Variações realistas de email
    variacao = random.choice([
        nome_limpo,
        nome_limpo + str(random.randint(1, 999)),
        nome_limpo + str(random.randint(1990, 2005)),
        nome_limpo.replace("a", "4").replace("e", "3").replace("i", "1"),
        nome_limpo + "_" + str(random.randint(10, 99)),
        nome_limpo + "." + str(random.randint(1, 99))
    ])
    
    dominio = random.choice(DOMINIOS_EMAIL)
    return f"{variacao}@{dominio}"

def gerar_telefone_brasileiro():
    """Gera um telefone brasileiro realista"""
    ddd = random.choice(DDDS_BRASIL)
    
    # 90% chance de ser celular (9XXXX-XXXX), 10% fixo (XXXX-XXXX)
    if random.random() < 0.9:
        # Celular (sempre começa com 9)
        numero = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
    else:
        # Fixo
        numero = f"{random.randint(2000, 5999)}{random.randint(1000, 9999)}"
    
    return f"{ddd}{numero}"

def gerar_cpf_ficticio():
    """Gera um CPF fictício (formato válido mas números aleatórios)"""
    # Gera 9 primeiros dígitos
    cpf = [random.randint(0, 9) for _ in range(9)]
    
    # Calcula primeiro dígito verificador
    soma = sum(cpf[i] * (10 - i) for i in range(9))
    resto = soma % 11
    digito1 = 0 if resto < 2 else 11 - resto
    cpf.append(digito1)
    
    # Calcula segundo dígito verificador
    soma = sum(cpf[i] * (11 - i) for i in range(10))
    resto = soma % 11
    digito2 = 0 if resto < 2 else 11 - resto
    cpf.append(digito2)
    
    return ''.join(map(str, cpf))

def gerar_ip_ficticio():
    """Gera um IP brasileiro realista"""
    # IPs de provedores brasileiros comuns
    ips_brasil = [
        f"189.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        f"177.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        f"201.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        f"200.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        f"179.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    ]
    return random.choice(ips_brasil)

def gerar_parametros_utm_reais(user_id, pacote):
    """
    Busca UTMs REAIS do Facebook primeiro, senão usa fictícios
    """
    
    # Tenta buscar UTMs REAIS
    utms_reais = buscar_utms_reais_do_backend()
    
    if utms_reais and utms_reais.get('utm_campaign'):
        # ENCONTROU UTMs REAIS!
        logger.info(f"🎯 USANDO UTMs REAIS do Facebook para User {user_id}")
        logger.info(f"📊 Campaign REAL: {utms_reais.get('utm_campaign')}")
        
        return {
            "src": None,
            "sck": None,
            "utm_source": utms_reais.get('utm_source', 'FB'),
            "utm_campaign": utms_reais.get('utm_campaign'),
            "utm_medium": utms_reais.get('utm_medium'),
            "utm_content": utms_reais.get('utm_content'),
            "utm_term": utms_reais.get('utm_term')
        }
    
    else:
        # FALLBACK: UTMs fictícios (seu código atual)
        logger.info(f"🔄 UTMs reais não encontrados, usando fictícios para User {user_id}")
        return gerar_utms_ficticios(user_id, pacote)

def buscar_utms_reais_do_backend():
    """
    Busca UTMs do backend Ngrok
    """
    try:
        # SUA URL do Ngrok
        backend_url = 'https://818a-45-174-82-157.ngrok-free.app/api/get-utms-recent'
        
        response = requests.get(backend_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                return data.get('utms', {})
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Erro ao buscar UTMs: {e}")
        return None

def gerar_utms_ficticios(user_id, pacote):
    """
    SEU SISTEMA ATUAL (fallback)
    """
    campaigns_reais = {
        "1": [
            f"Pack_Gostosinha_Brasil|{12345670000 + (user_id % 9999999)}",
            f"Vendas_Pack_Basico_Dec24|{12345680000 + (user_id % 9999999)}",
            f"Promocao_Gostosinha_2024|{12345690000 + (user_id % 9999999)}",
            f"Telegram_Pack_Simples|{12345700000 + (user_id % 9999999)}"
        ],
        "2": [
            f"Grupo_VIP_Exclusivo|{23456780000 + (user_id % 9999999)}",
            f"VIP_Access_Premium|{23456790000 + (user_id % 9999999)}",
            f"Vendas_Grupo_VIP_Dec|{23456800000 + (user_id % 9999999)}",
            f"Telegram_VIP_Brasil|{23456810000 + (user_id % 9999999)}"
        ],
        "3": [
            f"Namoradinha_Obediente|{34567890000 + (user_id % 9999999)}",
            f"Pack_Namoradinha_Premium|{34567900000 + (user_id % 9999999)}",
            f"Vendas_Namoradinha_2024|{34567910000 + (user_id % 9999999)}",
            f"Telegram_Namoradinha_BR|{34567920000 + (user_id % 9999999)}"
        ]
    }
    
    adsets_reais = [
        f"Publico_Masculino_18-45|{18000000000 + (user_id % 999999999)}",
        f"Interesse_Conteudo_Adulto|{18100000000 + (user_id % 999999999)}",
        f"Lookalike_Compradores_1pct|{18200000000 + (user_id % 999999999)}",
        f"Retargeting_Visitantes_Site|{18300000000 + (user_id % 999999999)}",
        f"Publico_Amplo_Brasil|{18400000000 + (user_id % 999999999)}",
        f"Interesse_Telegram_Packs|{18500000000 + (user_id % 999999999)}",
        f"Custom_Audience_Engajou|{18600000000 + (user_id % 999999999)}",
        f"Similares_Clientes_Ativos|{18700000000 + (user_id % 999999999)}"
    ]
    
    criativos_reais = [
        f"Video_Provocante_Telegram|{45000000000 + (user_id % 999999999)}",
        f"Carrossel_Tabela_Precos|{45100000000 + (user_id % 999999999)}",
        f"Story_Urgencia_Pack|{45200000000 + (user_id % 999999999)}",
        f"Reels_Seducao_Premium|{45300000000 + (user_id % 999999999)}",
        f"Imagem_Call_Action|{45400000000 + (user_id % 999999999)}",
        f"Video_Testimonial_Cliente|{45500000000 + (user_id % 999999999)}",
        f"Carrossel_Previsualizacao|{45600000000 + (user_id % 999999999)}",
        f"Story_Promocao_Limitada|{45700000000 + (user_id % 999999999)}"
    ]
    
    placements_reais = [
        "facebook_feeds", "instagram_feeds", "instagram_stories",
        "facebook_stories", "instagram_reels", "facebook_reels"
    ]
    
    # Escolhe baseado no user_id
    campaign_list = campaigns_reais.get(pacote, campaigns_reais["1"])
    campaign = campaign_list[user_id % len(campaign_list)]
    adset = adsets_reais[user_id % len(adsets_reais)]
    criativo = criativos_reais[user_id % len(criativos_reais)]
    placement = placements_reais[user_id % len(placements_reais)]
    
    return {
        "src": None,
        "sck": None,
        "utm_source": "FB",
        "utm_campaign": campaign,
        "utm_medium": adset,
        "utm_content": criativo,
        "utm_term": placement
    }

def criar_customer_baseado_userid(user_id):
    """Cria customer consistente baseado no user_id"""
    
    # Usa user_id como seed para dados consistentes
    random.seed(user_id)
    
    # Gera dados baseados no ID (sempre iguais para mesmo user)
    nome = gerar_nome_completo()
    email = gerar_email_ficticio(nome)
    telefone = gerar_telefone_brasileiro()
    
    # Restaura randomness normal
    random.seed()
    
    # CPF e IP baseados no user_id (sem random)
    cpf = gerar_cpf_baseado_userid(user_id)
    ip = gerar_ip_baseado_userid(user_id)
    
    return {
        "name": nome,
        "email": email, 
        "phone": telefone,
        "document": cpf,
        "country": "BR",
        "ip": ip
    }
    
def gerar_cpf_baseado_userid(user_id):
    """Gera CPF consistente baseado no user_id"""
    # Usa user_id para gerar primeiros 9 dígitos
    user_str = str(user_id).zfill(9)
    cpf = [int(d) for d in user_str[:9]]
    
    # Se user_id tem menos de 9 dígitos, completa
    while len(cpf) < 9:
        cpf.append((user_id + len(cpf)) % 10)
    
    # Calcula dígitos verificadores
    soma = sum(cpf[i] * (10 - i) for i in range(9))
    resto = soma % 11
    digito1 = 0 if resto < 2 else 11 - resto
    cpf.append(digito1)
    
    soma = sum(cpf[i] * (11 - i) for i in range(10))
    resto = soma % 11
    digito2 = 0 if resto < 2 else 11 - resto
    cpf.append(digito2)
    
    return ''.join(map(str, cpf))

def gerar_ip_baseado_userid(user_id):
    """Gera IP brasileiro consistente baseado no user_id"""
    # IP baseado no user_id mas sempre brasileiro
    base = user_id % 256
    segundo = (user_id // 256) % 256
    terceiro = (user_id // 65536) % 256
    
    # Prefixos brasileiros
    prefixos = [189, 177, 201, 200, 179]
    prefixo = prefixos[user_id % len(prefixos)]
    
    return f"{prefixo}.{segundo}.{terceiro}.{base if base > 0 else 1}"

def criar_produto_por_pacote(pacote):
    """Cria dados do produto baseado no pacote comprado"""
    produtos_config = {
        "1": {
            "id": "pack-gostosinha-001",
            "name": "Pack Gostosinha",
            "planId": "plan-gostosinha",
            "planName": "Acesso Pack Básico",
            "quantity": 1,
            "priceInCents": 1200  # R$ 12,00
        },
        "2": {
            "id": "pack-grupovip-002", 
            "name": "Grupo VIP",
            "planId": "plan-grupovip",
            "planName": "Acesso Grupo VIP",
            "quantity": 1,
            "priceInCents": 1800  # R$ 18,00
        },
        "3": {
            "id": "pack-namoradinha-003",
            "name": "Namoradinha Obediente",
            "planId": "plan-namoradinha", 
            "planName": "Acesso Namoradinha",
            "quantity": 1,
            "priceInCents": 2400  # R$ 24,00
        }
    }
    
    return produtos_config.get(pacote, produtos_config["1"])

def calcular_comissao(valor_centavos):
    """Calcula comissão realista (taxa PIX de 3% + R$ 0,50)"""
    taxa_fixa = 50  # R$ 0,50 em centavos
    taxa_percentual = int(valor_centavos * 0.03)  # 3%
    gateway_fee = taxa_fixa + taxa_percentual
    user_commission = valor_centavos - gateway_fee
    
    return {
        "totalPriceInCents": valor_centavos,
        "gatewayFeeInCents": gateway_fee,
        "userCommissionInCents": user_commission,
        "currency": "BRL"
    }
    
def criar_produto_desconto_especial(valor_centavos):
    """
    Cria dados do produto para desconto especial
    Usa o valor REAL pago, não o valor do pacote original
    """
    return {
        "id": "pack-namoradinha-desconto",
        "name": "Namoradinha Desconto Especial", 
        "planId": "plan-namoradinha-promo",
        "planName": "Acesso Namoradinha - Promoção R$ 15",
        "quantity": 1,
        "priceInCents": valor_centavos  # Valor REAL pago (1500 = R$ 15)
    }

# ADICIONE esta nova função para enviar desconto:

def enviar_venda_utmify_desconto(user_id, valor_centavos, status="waiting_payment", created_at=None, approved_date=None):
    """
    Envia venda de desconto para UTMIFY com valor REAL
    """
    
    # Evita envios duplicados
    with lock:
        venda_key = f"{user_id}_desconto_{valor_centavos}_{status}"
        if venda_key in vendas_enviadas:
            logger.info(f"🔄 Venda desconto já enviada para UTMIFY: {venda_key}")
            return True
        vendas_enviadas.add(venda_key)
    
    try:
        # Produto com valor REAL do desconto
        produto = criar_produto_desconto_especial(valor_centavos)
        
        # Customer baseado no user_id
        customer = criar_customer_baseado_userid(user_id)
        
        # UTM parameters (simula pacote 3 mas com valor correto)
        tracking_params = gerar_parametros_utm_reais(user_id, "3")
        
        # Comissão baseada no valor REAL
        commission = calcular_comissao(valor_centavos)
        
        # Datas
        if created_at is None:
            created_at = datetime.utcnow()
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            
        if status == "paid" and approved_date is None:
            approved_date = datetime.utcnow()
        elif approved_date and isinstance(approved_date, str):
            approved_date = datetime.fromisoformat(approved_date.replace("Z", "+00:00"))
        
        # Order ID único para desconto
        timestamp = int(time.time())
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        order_id = f"tg-{user_id}-desconto-{status}-{timestamp}-{random_suffix}"
        
        # Payload com valor CORRETO
        payload = {
            "orderId": order_id,
            "platform": PLATFORM_NAME,
            "paymentMethod": "pix",
            "status": status,
            "createdAt": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "approvedDate": approved_date.strftime("%Y-%m-%d %H:%M:%S") if approved_date else None,
            "refundedAt": None,
            "customer": customer,
            "products": [produto],  # Produto com valor R$ 15
            "trackingParameters": tracking_params,
            "commission": commission,  # Comissão baseada em R$ 15
            "isTest": False
        }
        
        # Headers
        headers = {
            "x-api-token": UTMIFY_API_TOKEN,
            "Content-Type": "application/json"
        }
        
        logger.info(f"📤 Enviando DESCONTO para UTMIFY - User: {user_id}, Valor: R$ {valor_centavos/100:.2f}, Status: {status}")
        logger.info(f"📤 Produto: {produto['name']} - Preço: R$ {valor_centavos/100:.2f}")
        logger.info(f"📤 Customer: {customer['name']} ({customer['email']})")
        
        # Envia para UTMIFY
        response = requests.post(
            UTMIFY_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        logger.info(f"📊 UTMIFY Desconto Response: {response.status_code} - {response.text}")
        
        if response.status_code == 200 or response.status_code == 201:
            logger.info(f"✅ Desconto R$ {valor_centavos/100:.2f} enviado com sucesso para UTMIFY!")
            return True
        else:
            logger.error(f"❌ Erro ao enviar desconto para UTMIFY: {response.status_code} - {response.text}")
            with lock:
                vendas_enviadas.discard(venda_key)
            return False
            
    except Exception as e:
        logger.error(f"❌ Exceção ao enviar desconto para UTMIFY: {e}")
        with lock:
            vendas_enviadas.discard(venda_key)
        return False

# ADICIONE estas funções específicas para desconto:

def enviar_pix_desconto_gerado(user_id, valor_centavos=1500):
    """Envia evento de PIX desconto gerado (R$ 15) para UTMIFY"""
    return enviar_venda_utmify_desconto(user_id, valor_centavos, status="waiting_payment")

def enviar_pix_desconto_pago(user_id, valor_centavos=1500):
    """Envia evento de PIX desconto pago (R$ 15) para UTMIFY"""
    return enviar_venda_utmify_desconto(user_id, valor_centavos, status="paid")

def enviar_venda_utmify(user_id, pacote, status="waiting_payment", created_at=None, approved_date=None):
    """
    Envia dados de venda para UTMIFY - VERSÃO MELHORADA
    """
    
    # Evita envios duplicados
    with lock:
        venda_key = f"{user_id}_{pacote}_{status}"
        if venda_key in vendas_enviadas:
            logger.info(f"🔄 Venda já enviada para UTMIFY: {venda_key}")
            return True
        vendas_enviadas.add(venda_key)
    
    try:
        # Dados do produto
        produto = criar_produto_por_pacote(pacote)
        
        # Customer baseado no user_id (NOVO - dinâmico)
        customer = criar_customer_baseado_userid(user_id)
        
        # UTM parameters baseados no usuário (NOVO - dinâmico)
        tracking_params = gerar_parametros_utm_reais(user_id, pacote)
        
        # Comissão
        commission = calcular_comissao(produto["priceInCents"])
        
        # Datas
        if created_at is None:
            created_at = datetime.utcnow()
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            
        if status == "paid" and approved_date is None:
            approved_date = datetime.utcnow()
        elif approved_date and isinstance(approved_date, str):
            approved_date = datetime.fromisoformat(approved_date.replace("Z", "+00:00"))
        
        # Order ID único (MELHORADO)
        timestamp = int(time.time())
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        order_id = f"tg-{user_id}-{pacote}-{status}-{timestamp}-{random_suffix}"
        
        # Payload
        payload = {
            "orderId": order_id,
            "platform": PLATFORM_NAME,
            "paymentMethod": "pix",
            "status": status,
            "createdAt": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "approvedDate": approved_date.strftime("%Y-%m-%d %H:%M:%S") if approved_date else None,
            "refundedAt": None,
            "customer": customer,
            "products": [produto],
            "trackingParameters": tracking_params,
            "commission": commission,
            "isTest": False
        }
        
        # Headers
        headers = {
            "x-api-token": UTMIFY_API_TOKEN,
            "Content-Type": "application/json"
        }
        
        logger.info(f"📤 Enviando venda DINÂMICA para UTMIFY - User: {user_id}, Pacote: {pacote}, Status: {status}")
        logger.info(f"📤 Customer: {customer['name']} ({customer['email']}) - IP: {customer['ip']}")
        logger.info(f"📤 UTM Source: {tracking_params['utm_source']} | Campaign: {tracking_params['utm_campaign']}")
        
        # Envia para UTMIFY
        response = requests.post(
            UTMIFY_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        logger.info(f"📊 UTMIFY Response: {response.status_code} - {response.text}")
        
        if response.status_code == 200 or response.status_code == 201:
            logger.info(f"✅ Venda DINÂMICA enviada com sucesso para UTMIFY!")
            return True
        else:
            logger.error(f"❌ Erro ao enviar para UTMIFY: {response.status_code} - {response.text}")
            with lock:
                vendas_enviadas.discard(venda_key)
            return False
            
    except Exception as e:
        logger.error(f"❌ Exceção ao enviar para UTMIFY: {e}")
        with lock:
            vendas_enviadas.discard(venda_key)
        return False

def enviar_pix_gerado(user_id, pacote):
    """Envia evento de PIX gerado (waiting_payment) para UTMIFY"""
    return enviar_venda_utmify(user_id, pacote, status="waiting_payment")

def enviar_pix_pago(user_id, pacote):
    """Envia evento de PIX pago (paid) para UTMIFY"""
    return enviar_venda_utmify(user_id, pacote, status="paid")

def enviar_pix_recusado(user_id, pacote):
    """Envia evento de PIX recusado (refused) para UTMIFY"""
    return enviar_venda_utmify(user_id, pacote, status="refused")

# Função para teste do sistema
def testar_sistema_utmify():
    """Testa o sistema enviando dados fictícios"""
    logger.info("🧪 Testando sistema UTMIFY...")
    
    # Teste 1: PIX gerado
    result1 = enviar_pix_gerado(user_id=123456, pacote="2")
    logger.info(f"Teste 1 (PIX gerado): {'✅' if result1 else '❌'}")
    
    # Teste 2: PIX pago
    result2 = enviar_pix_pago(user_id=123456, pacote="2") 
    logger.info(f"Teste 2 (PIX pago): {'✅' if result2 else '❌'}")
    
    return result1 and result2

if __name__ == "__main__":
    # Configura logging para teste
    logging.basicConfig(level=logging.INFO)
    
    # Executa teste
    testar_sistema_utmify()
    print("\n🎯 Sistema UTMIFY configurado!")
    print("📋 Não esqueça de:")
    print("1. Configurar UTMIFY_API_TOKEN com seu token real")
    print("2. Testar com isTest=True primeiro")
    print("3. Integrar com o sistema de pagamentos")