# backend_utm.py - ARQUIVO NOVO PARA CRIAR
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import time
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Variável para guardar os UTMs
utm_storage = {}

@app.route('/')
def home():
    return jsonify({
        "status": "Backend funcionando!",
        "total_utms": len(utm_storage)
    })

@app.route('/api/save-utms', methods=['POST'])
def salvar_utms():
    try:
        # Adiciona headers CORS manualmente
        response_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }
        
        data = request.get_json()
        print(f"\nRECEBENDO UTMs DO FACEBOOK:")
        print(f"Campaign: {data.get('utm_campaign')}")
        print(f"Content: {data.get('utm_content')}")
        
        # Gera ID único
        session_id = str(int(time.time() * 1000))
        
        # Salva os UTMs
        utm_data = {
            'utm_source': data.get('utm_source', 'FB'),
            'utm_campaign': data.get('utm_campaign', ''),
            'utm_medium': data.get('utm_medium', ''), 
            'utm_content': data.get('utm_content', ''),
            'utm_term': data.get('utm_term', ''),
            'timestamp': datetime.now().isoformat()
        }
        
        utm_storage[session_id] = utm_data
        
        print(f"UTMs salvos! Total: {len(utm_storage)}")
        
        response = jsonify({
            'success': True,
            'session_id': session_id,
            'utm_campaign': utm_data['utm_campaign']
        })
        
        # Adiciona headers à resposta
        for key, value in response_headers.items():
            response.headers[key] = value
            
        return response
        
    except Exception as e:
        print(f"Erro: {e}")
        response = jsonify({'error': str(e)})
        for key, value in response_headers.items():
            response.headers[key] = value
        return response, 400

@app.route('/api/get-utms-recent', methods=['GET'])
def buscar_utms_recentes():
    try:
        print(f"\nBOT BUSCANDO UTMs...")
        
        # Pega o UTM mais recente (últimas 2 horas)
        cutoff_time = datetime.now() - timedelta(hours=2)
        utms_recentes = None
        
        for session_id, utm_data in reversed(utm_storage.items()):
            timestamp = datetime.fromisoformat(utm_data['timestamp'])
            if timestamp > cutoff_time:
                utms_recentes = utm_data
                break
        
        if utms_recentes and utms_recentes.get('utm_campaign'):
            print(f"UTMs encontrados!")
            print(f"Campaign: {utms_recentes['utm_campaign']}")
            
            return jsonify({
                'success': True,
                'utms': utms_recentes
            })
        else:
            print(f"Nenhum UTM encontrado")
            return jsonify({
                'success': False,
                'message': 'Nenhum UTM encontrado'
            }), 404
            
    except Exception as e:
        print(f"Erro: {e}")
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    print("BACKEND INICIANDO...")
    print("Para testar, acesse: http://localhost:5002")
    app.run(host='0.0.0.0', port=5002, debug=True)