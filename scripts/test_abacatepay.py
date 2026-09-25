import os
import sys
import json
import logging

# Adiciona o diretório raiz ao path para podermos importar `app`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)

try:
    import abacatepay
except ImportError:
    logging.error("Biblioteca 'abacatepay' não encontrada. Verifique se ela foi instalada.")
    sys.exit(1)

from app import payment, db

def test_create_checkout():
    logging.info("Testando criação de checkout...")
    if not os.environ.get("ABACATEPAY_API_KEY"):
        logging.error("ABACATEPAY_API_KEY não está definida no arquivo .env!")
        return False
        
    try:
        # Testa criando um checkout para o plano Owner (id 1, slug 'owner')
        # NOTA: AbacatePay exige um domínio real na URL de retorno (rejeita localhost). Usando um de exemplo.
        url = payment.create_checkout(user_id=1, plan_slug="owner", return_url="https://exemplo.com.br/")
        logging.info(f"Sucesso! URL de checkout gerada: {url}")
        
        # Inspeciona o banco de dados
        con = db.get_con()
        payment_row = con.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        
        if payment_row:
            logging.info(f"Registro no banco de dados criado: ID da fatura = {payment_row['billing_id']}, Status = {payment_row['status']}")
        return True
    except Exception as e:
        import traceback
        logging.error(f"Erro ao criar checkout: {e}")
        traceback.print_exc()
        if hasattr(e, 'response'):
            logging.error(f"Response: {e.response.text}")
        return False

def test_webhook_simulation():
    logging.info("\nTestando processamento do webhook...")
    
    con = db.get_con()
    # Pega a ultima fatura gerada para simular pagamento
    payment_row = con.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    
    if not payment_row:
        logging.warning("Nenhum pagamento pendente no banco de dados para testar webhook.")
        return False
        
    billing_id = payment_row["billing_id"]
    logging.info(f"Simulando webhook billing.paid para a fatura {billing_id}...")
    
    # Payload simulado do AbacatePay
    payload = {
        "event": "billing.paid",
        "data": {
            "id": billing_id,
            "status": "PAID"
        }
    }
    
    success = payment.process_webhook(payload)
    if success:
        logging.info("Webhook processado com sucesso!")
        
        # Verifica se atualizou o status
        con = db.get_con()
        updated = con.execute("SELECT * FROM payments WHERE id = ?", (payment_row["id"],)).fetchone()
        user = con.execute("SELECT * FROM users WHERE id = ?", (payment_row["user_id"],)).fetchone()
        con.close()
        
        logging.info(f"Novo status do pagamento: {updated['status']}")
        if user:
            logging.info(f"Novo plan_id do usuario: {user['plan_id']} (deveria ser {payment_row['plan_id']})")
        return True
    else:
        logging.error("Falha ao processar webhook.")
        return False

if __name__ == "__main__":
    logging.info("--- INICIANDO TESTES DO ABACATEPAY ---")
    if test_create_checkout():
        test_webhook_simulation()
    logging.info("--- FIM DOS TESTES ---")
