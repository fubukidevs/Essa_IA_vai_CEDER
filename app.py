# app.py - ARQUIVO MÃE - Execute apenas este arquivo
import subprocess
import threading
import time
import os
import sys
import signal
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Lista para armazenar os processos
processos = []

def executar_backend():
    """Executa o backend_utm.py"""
    try:
        logger.info("🚀 Iniciando backend_utm.py...")
        processo = subprocess.Popen([
            sys.executable, 'backend_utm.py'
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        processos.append(processo)
        
        # Mostra output em tempo real
        for linha in iter(processo.stdout.readline, ''):
            if linha:
                print(f"[BACKEND] {linha.strip()}")
        
        processo.wait()
        
    except Exception as e:
        logger.error(f"❌ Erro ao executar backend: {e}")

def executar_bot():
    """Executa o bot.py"""
    try:
        logger.info("🤖 Iniciando bot.py...")
        processo = subprocess.Popen([
            sys.executable, 'bot.py'
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        processos.append(processo)
        
        # Mostra output em tempo real
        for linha in iter(processo.stdout.readline, ''):
            if linha:
                print(f"[BOT] {linha.strip()}")
        
        processo.wait()
        
    except Exception as e:
        logger.error(f"❌ Erro ao executar bot: {e}")

def verificar_arquivos():
    """Verifica se todos os arquivos necessários existem"""
    arquivos_necessarios = [
        'backend_utm.py',
        'bot.py', 
        'pagamento.py',
        'utmify_tracker.py'
    ]
    
    arquivos_faltando = []
    for arquivo in arquivos_necessarios:
        if not os.path.exists(arquivo):
            arquivos_faltando.append(arquivo)
    
    if arquivos_faltando:
        logger.error(f"❌ Arquivos não encontrados: {arquivos_faltando}")
        logger.error("📁 Certifique-se de que todos os arquivos estão na mesma pasta!")
        return False
    
    logger.info("✅ Todos os arquivos necessários encontrados!")
    return True

def signal_handler(sig, frame):
    """Manipula sinais para parar os processos filhos"""
    logger.info("🛑 Recebido sinal de parada. Encerrando processos...")
    
    for processo in processos:
        if processo.poll() is None:  # Se processo ainda está rodando
            logger.info(f"🔄 Parando processo PID: {processo.pid}")
            processo.terminate()
            
            # Aguarda 5 segundos para terminar graciosamente
            try:
                processo.wait(timeout=5)
                logger.info(f"✅ Processo {processo.pid} encerrado")
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ Forçando encerramento do processo {processo.pid}")
                processo.kill()
    
    logger.info("👋 Todos os processos encerrados. Saindo...")
    sys.exit(0)

def mostrar_status():
    """Mostra status dos processos a cada 30 segundos"""
    while True:
        time.sleep(30)
        
        backend_status = "🟢 Rodando" if len(processos) > 0 and processos[0].poll() is None else "🔴 Parado"
        bot_status = "🟢 Rodando" if len(processos) > 1 and processos[1].poll() is None else "🔴 Parado" 
        
        logger.info(f"📊 STATUS - Backend: {backend_status} | Bot: {bot_status}")

def main():
    """Função principal"""
    print("="*60)
    print("🚀 SISTEMA TELEGRAM BOT + BACKEND UTM - INICIANDO")
    print("="*60)
    
    # Registra manipulador de sinais
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Verifica arquivos
    if not verificar_arquivos():
        return
    
    try:
        logger.info("🔄 Iniciando processos em threads separadas...")
        
        # Thread para backend
        thread_backend = threading.Thread(target=executar_backend, daemon=True)
        thread_backend.start()
        logger.info("✅ Thread do backend iniciada")
        
        # Aguarda 3 segundos antes de iniciar o bot
        time.sleep(3)
        
        # Thread para bot
        thread_bot = threading.Thread(target=executar_bot, daemon=True)
        thread_bot.start()
        logger.info("✅ Thread do bot iniciada")
        
        # Thread para mostrar status
        thread_status = threading.Thread(target=mostrar_status, daemon=True)
        thread_status.start()
        
        print("\n" + "="*60)
        print("✅ SISTEMA INICIADO COM SUCESSO!")
        print("📊 Backend UTM: http://localhost:5002")
        print("🤖 Bot Telegram: Ativo")
        print("💰 Sistema PIX: Ativo") 
        print("📈 Dashboard: http://localhost:5000")
        print("\n🔄 Pressione Ctrl+C para parar tudo")
        print("="*60)
        
        # Aguarda as threads terminarem
        thread_backend.join()
        thread_bot.join()
        
    except KeyboardInterrupt:
        logger.info("🛑 Interrupção detectada (Ctrl+C)")
        signal_handler(signal.SIGINT, None)
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
        signal_handler(signal.SIGTERM, None)

if __name__ == "__main__":
    main()