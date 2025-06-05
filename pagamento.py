import requests
import json
import logging
import asyncio
from flask import Flask, request, jsonify
import threading

# ===== CONFIGURE SUAS INFORMAÇÕES AQUI =====
PUSHINPAY_TOKEN = "32092|XcHAjtbPbF5OuXAjXY8UWmiLPjG0bvqdlsgeKNJw0069cb21"  # Seu token
WEBHOOK_URL = "https://fc8d-45-174-82-157.ngrok-free.app"                      # Seu domínio
IS_SANDBOX = False                                                             # True = teste, False = produção

# Substitua pelos seus links reais de acesso
LINKS_ACESSO = {
    "1": "https://pack_gostosinha.com",     # Link do pack Gostosinha (R$ 12)
    "2": "https://pack_grupovip.com",           # Link do Grupo VIP (R$ 18)  
    "3": "https://pack_zap.com"                  # Seu WhatsApp (R$ 24)
}
# =============================================

logger = logging.getLogger(__name__)

# Variáveis para controlar pagamentos
pagamentos_pendentes = {}
usuario_pagamento = {}
callback_pagamento = None

# Valores dos pacotes em centavos
valores_pacotes = {
    "1": 1200,  # R$ 12,00 = 1200 centavos (Gostosinha)
    "2": 1800,  # R$ 18,00 = 1800 centavos (Grupo VIP)  
    "3": 2400   # R$ 24,00 = 2400 centavos (Namoradinha)
}

# URL da API (muda se for teste ou produção)
if IS_SANDBOX:
    api_url = "https://api-sandbox.pushinpay.com.br"
else:
    api_url = "https://api.pushinpay.com.br"

# Headers para requests da API
headers = {
    'Authorization': f'Bearer {PUSHINPAY_TOKEN}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

def detectar_pacote_escolhido(mensagem_usuario):
    """
    Detecta qual pacote o usuário quer baseado na mensagem
    Lista COMPLETA com palavras que leads reais falariam
    Retorna: "1", "2", "3" ou None
    """
    msg = mensagem_usuario.lower()
    
    # ========================================
    # PACOTE 1 - GOSTOSINHA (R$ 12) - MAIS BARATO
    # ========================================
    palavras_pacote1 = [
        # Valor específico
        "12 reais", "de 12", "12,00", "r$ 12", "rs 12", "12 real", "doze reais",
        
        # Nome do pacote
        "gostosinha", "pack gostosinha", "pacote gostosinha", "gostosa",
        
        # Posição/ordem
        "primeiro", "1º", "1°", "o primeiro", "quero o primeiro", "primeiro pacote",
        "pacote 1", "opcao 1", "opção 1", "numero 1", "número 1",
        
        # Características (mais barato)
        "mais barato", "barato", "baratinho", "mais em conta", "menor preço", 
        "menor valor", "o barato", "o baratinho", "conta menos", "sai menos",
        "economico", "econômico", "promocional", "mais acessivel", "mais acessível",
        
        # Formas casuais
        "esse de 12", "o de 12", "esse barato", "o barato", "vou no barato",
        "pego o barato", "vou de barato", "esse mais baixo", "valor menor",
        "o menor", "esse menor", "só esse", "so esse", "esse simples"
    ]
    
    # ========================================
    # PACOTE 2 - GRUPO VIP (R$ 18) - DO MEIO  
    # ========================================
    palavras_pacote2 = [
        # Valor específico
        "18 reais", "de 18", "18,00", "r$ 18", "rs 18", "18 real", "dezoito reais",
        
        # Nome do pacote
        "grupo vip", "vip", "pack vip", "pacote vip", "grupo", "grupinho",
        
        # Posição/ordem
        "segundo", "2º", "2°", "o segundo", "quero o segundo", "segundo pacote",
        "pacote 2", "opcao 2", "opção 2", "numero 2", "número 2",
        
        # Características (do meio)
        "do meio", "o do meio", "meio termo", "intermediario", "intermediário",
        "mediano", "medio", "médio", "entre os dois", "no meio", "o meio",
        "nem barato nem caro", "equilibrado", "razoavel", "razoável",
        
        # Formas casuais
        "esse de 18", "o de 18", "esse do meio", "vou no meio", "pego o meio",
        "vou de medio", "vou de médio", "esse intermediário", "o segundo ai",
        "aquele do meio", "o central", "esse central"
    ]
    
    # ========================================
    # PACOTE 3 - NAMORADINHA (R$ 24) - MAIS CARO
    # ========================================
    palavras_pacote3 = [
        # Valor específico
        "24 reais", "de 24", "24,00", "r$ 24", "rs 24", "24 real", "vinte e quatro",
        
        # Nome do pacote
        "namoradinha", "namora", "namorada", "pack namoradinha", "pacote namoradinha",
        "namoradinha obediente", "sua namoradinha", "ser sua namoradinha",
        
        # Posição/ordem
        "terceiro", "3º", "3°", "o terceiro", "quero o terceiro", "terceiro pacote",
        "pacote 3", "opcao 3", "opção 3", "numero 3", "número 3",
        "ultimo", "último", "ultima", "última", "o ultimo", "o último",
        "ultimo pacote", "última opção", "ultima opcao", "por ultimo", "por último",
        
        # Características (mais caro/completo)
        "mais caro", "caro", "carinho", "mais completo", "completo", "premium",
        "o caro", "o carinho", "top", "o top", "melhor", "o melhor",
        "mais valor", "maior valor", "o maior", "tudo", "completo mesmo",
        "o mais completo", "all in", "full", "tudinho", "tudo mesmo",
        "investment", "investimento", "vale a pena", "capricha",
        
        # Formas casuais
        "esse de 24", "o de 24", "esse caro", "vou no caro", "pego o caro",
        "vou de caro", "esse mais alto", "valor maior", "o maior valor",
        "esse premium", "o premium", "vou all in", "meto o louco",
        "vou de tudo", "quero tudo", "o completo", "esse completo",
        "o de cima", "esse de cima", "o final", "esse final"
    ]
    
    # Verifica cada pacote na ordem (importante: do mais específico para o menos)
    if any(palavra in msg for palavra in palavras_pacote1):
        return "1"
    elif any(palavra in msg for palavra in palavras_pacote2):
        return "2"  
    elif any(palavra in msg for palavra in palavras_pacote3):
        return "3"
    
    return None

# TAMBÉM ATUALIZE a lista na função detectar_interesse_inteligente():

# Todas as palavras dos pacotes específicos (para não perguntar quando já especificou)
palavras_pacote_especifico = [
    # Pacote 1
    "12 reais", "de 12", "gostosinha", "primeiro", "12,00", "pacote 1", "mais barato",
    "barato", "baratinho", "o primeiro", "1º", "opcao 1", "opção 1",
    
    # Pacote 2  
    "18 reais", "de 18", "grupo vip", "vip", "segundo", "18,00", "pacote 2",
    "do meio", "o do meio", "medio", "médio", "o segundo", "2º", "opcao 2", "opção 2",
    
    # Pacote 3
    "24 reais", "de 24", "namoradinha", "terceiro", "24,00", "pacote 3", "mais caro",
    "caro", "ultimo", "último", "ultima", "última", "o terceiro", "o ultimo", "3º",
    "opcao 3", "opção 3", "completo", "premium", "top", "melhor", "tudo",
    
    # Nomes dos pacotes
    "pack gostosinha", "pack vip", "pack namoradinha", "namora", "grupo"
]

def criar_pix_pagamento(user_id, pacote):
    """
    Cria um PIX na PushinPay para o usuário
    Retorna: dados do PIX ou None se erro
    """
    try:
        if pacote not in valores_pacotes:
            logger.error(f"Pacote inválido: {pacote}")
            return None
            
        valor_centavos = valores_pacotes[pacote]
        
        # Cancela pagamento anterior se existir
        if user_id in usuario_pagamento:
            old_id = usuario_pagamento[user_id]
            if old_id in pagamentos_pendentes:
                del pagamentos_pendentes[old_id]
                logger.info(f"🗑️ Removido pagamento anterior: {old_id}")
            del usuario_pagamento[user_id]
        
        # Dados para enviar para API
        payload = {
            "value": valor_centavos,
            "webhook_url": f"{WEBHOOK_URL}/webhook"
        }
        
        logger.info(f"📡 Criando PIX - User: {user_id}, Pacote: {pacote}, Valor: {valor_centavos}")
        logger.info(f"📡 Webhook URL: {WEBHOOK_URL}/webhook")
        
        # Faz request para PushinPay
        response = requests.post(
            f"{api_url}/api/pix/cashIn",
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        
        logger.info(f"📊 Status da API: {response.status_code}")
        logger.info(f"📊 Resposta da API: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            transaction_id = data.get('id')
            
            if transaction_id:
                # Salva informações do pagamento
                pagamentos_pendentes[transaction_id] = {
                    'user_id': user_id,
                    'pacote': pacote,
                    'valor': valor_centavos
                }
                usuario_pagamento[user_id] = transaction_id
                
                # LOGS DE DEBUG
                logger.info(f"💾 Pagamento salvo - ID: {transaction_id}")
                logger.info(f"💾 User: {user_id}, Pacote: {pacote}")
                logger.info(f"💾 Total pagamentos pendentes: {len(pagamentos_pendentes)}")
                logger.info(f"💾 IDs pendentes: {list(pagamentos_pendentes.keys())}")
                
                return {
                    'codigo_pix': data.get('qr_code'),
                    'valor_reais': valor_centavos / 100,
                    'pacote': pacote,
                    'transaction_id': transaction_id
                }
            else:
                logger.error("❌ Transaction ID não encontrado na resposta da API")
                return None
        else:
            logger.error(f"❌ Erro na API: {response.status_code} - {response.text}")
            return None
        
    except Exception as e:
        logger.error(f"❌ Erro ao criar PIX: {e}")
        return None

# Flask app para receber webhooks
webhook_app = Flask(__name__)

@webhook_app.route('/webhook', methods=['POST', 'GET'])
def receber_webhook():
    """
    Recebe confirmação de pagamento da PushinPay
    """
    try:
        # NOVO: Trata tanto GET quanto POST
        if request.method == 'GET':
            # Para GET, pega dados da query string
            data = {
                'status': request.args.get('status'),
                'id': request.args.get('id')
            }
            content_type = 'application/x-www-form-urlencoded'
        else:
            # Para POST, tenta diferentes formatos
            content_type = request.headers.get('Content-Type', '')
            
            if 'application/json' in content_type:
                data = request.get_json()
            elif 'application/x-www-form-urlencoded' in content_type:
                data = request.form.to_dict()
            else:
                # Tenta como texto e converte para JSON
                raw_data = request.get_data(as_text=True)
                try:
                    data = json.loads(raw_data)
                except:
                    data = {}
        
        logger.info(f"🎯 Webhook recebido - Method: {request.method}, Content-Type: {content_type}")
        logger.info(f"🎯 Dados recebidos: {data}")
        
        if not data or not data.get('status') or not data.get('id'):
            logger.warning("⚠️ Webhook vazio ou sem dados essenciais")
            return jsonify({"status": "ok"}), 200
        
        # Verifica se pagamento foi confirmado
        status = data.get('status')
        transaction_id = data.get('id')
        
        logger.info(f"🔍 Verificando pagamento - Status: {status}, ID: {transaction_id}")
        logger.info(f"🔍 Pagamentos pendentes disponíveis: {list(pagamentos_pendentes.keys())}")
        logger.info(f"🔍 Total pendentes: {len(pagamentos_pendentes)}")
        
        if status == 'paid':
            # Primeiro tenta encontrar exato
            found_transaction = None
            found_id = None
            
            if transaction_id in pagamentos_pendentes:
                found_transaction = pagamentos_pendentes[transaction_id]
                found_id = transaction_id
                logger.info(f"✅ ID encontrado exato: {transaction_id}")
            else:
                # Se não encontrou, procura ignorando case
                for pending_id, pending_data in pagamentos_pendentes.items():
                    if pending_id.lower() == transaction_id.lower():
                        found_transaction = pending_data
                        found_id = pending_id
                        logger.info(f"✅ ID encontrado com case diferente: {pending_id} = {transaction_id}")
                        break
            
            if found_transaction:
                # Pagamento confirmado!
                user_id = found_transaction['user_id']
                pacote = found_transaction['pacote']
                valor = found_transaction['valor']
                
                logger.info(f"🎉 PAGAMENTO CONFIRMADO!")
                logger.info(f"🎉 User: {user_id}")
                logger.info(f"🎉 Pacote: {pacote}")
                logger.info(f"🎉 Valor: R$ {valor/100:.2f}")
                
                # Remove da lista de pendentes usando o ID correto
                del pagamentos_pendentes[found_id]
                if user_id in usuario_pagamento:
                    del usuario_pagamento[user_id]
                
                logger.info(f"🧹 Pagamento removido dos pendentes - Restam: {len(pagamentos_pendentes)}")
                
                # Chama função de callback (que enviará o acesso)
                if callback_pagamento:
                    logger.info(f"📞 Chamando callback para liberação de acesso...")
                    try:
                        # Tenta criar task no loop existente
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Se o loop está rodando, agenda para execução
                            loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(callback_pagamento(user_id, pacote))
                            )
                            logger.info(f"📞 Callback agendado no loop principal")
                        else:
                            # Se não tem loop, cria um novo
                            asyncio.create_task(callback_pagamento(user_id, pacote))
                            logger.info(f"📞 Callback criado como task")
                    except RuntimeError:
                        # Se não conseguir acessar o loop, usa threading
                        import threading
                        def run_callback():
                            try:
                                asyncio.run(callback_pagamento(user_id, pacote))
                                logger.info(f"📞 Callback executado com sucesso via thread")
                            except Exception as e:
                                logger.error(f"❌ Erro no callback via thread: {e}")
                        
                        thread = threading.Thread(target=run_callback, daemon=True)
                        thread.start()
                        logger.info(f"📞 Callback executado em thread separada")
                    except Exception as e:
                        logger.error(f"❌ Erro geral no callback: {e}")
                else:
                    logger.error("❌ Callback não configurado!")
                    
            else:
                logger.warning(f"⚠️ Transaction ID {transaction_id} NÃO ENCONTRADO!")
                logger.warning(f"⚠️ IDs disponíveis: {list(pagamentos_pendentes.keys())}")
                
        else:
            logger.info(f"📊 Status recebido: {status} (aguardando 'paid')")
        
        return jsonify({"status": "ok", "received": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ERRO NO WEBHOOK: {e}")
        logger.error(f"❌ Request method: {request.method}")
        logger.error(f"❌ Request args: {dict(request.args)}")
        return jsonify({"error": str(e), "status": "error"}), 200

@webhook_app.route('/webhook', methods=['GET'])
def webhook_test():
    """Teste do webhook"""
    return jsonify({
        "status": "webhook_ativo", 
        "pagamentos_pendentes": len(pagamentos_pendentes),
        "ids_pendentes": list(pagamentos_pendentes.keys())
    }), 200

def iniciar_servidor_webhook():
    """Inicia o servidor para receber webhooks"""
    def executar():
        try:
            webhook_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"❌ Erro no servidor webhook: {e}")
    
    thread = threading.Thread(target=executar, daemon=True)
    thread.start()
    logger.info("🎯 Servidor webhook iniciado na porta 5001")
    logger.info(f"🎯 URL webhook: {WEBHOOK_URL}/webhook")

def definir_callback_pagamento(funcao_callback):
    """
    Define a função que será chamada quando pagamento for confirmado
    """
    global callback_pagamento
    callback_pagamento = funcao_callback
    logger.info("📞 Callback de pagamento configurado")

def formatar_resposta_pix(dados_pix):
    """
    Formata as mensagens que o bot vai enviar
    Retorna: (mensagem1, codigo_pix)
    """
    nomes_pacotes = {
        "1": "Gostosinha",
        "2": "Grupo VIP", 
        "3": "Namoradinha"
    }
    
    pacote = dados_pix['pacote']
    nome_pacote = nomes_pacotes.get(pacote, f"Pacote {pacote}")
    valor = dados_pix['valor_reais']
    codigo = dados_pix['codigo_pix']
    
    mensagem = f"ta bom amor vou te enviar o pix aqui em baixo, é pix copia e cola ta bom?"
    
    return mensagem, codigo

# Função para debug - verificar status de pagamentos
def debug_pagamentos():
    """Mostra status atual dos pagamentos"""
    logger.info(f"🔍 DEBUG - Pagamentos pendentes: {len(pagamentos_pendentes)}")
    for tid, info in pagamentos_pendentes.items():
        logger.info(f"🔍 ID: {tid} | User: {info['user_id']} | Pacote: {info['pacote']}")

if __name__ == "__main__":
    # Teste do sistema
    logger.info("🧪 Testando sistema de pagamento...")
    iniciar_servidor_webhook()
    print("Sistema de pagamento iniciado!")
    print(f"Webhook ativo em: {WEBHOOK_URL}/webhook")
    print("Pressione Ctrl+C para parar")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("Sistema parado!")