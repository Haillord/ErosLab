"""
Тест Groq API ключа (минимальный)
"""

import requests
import json

# Вставь сюда свой ключ
GROQ_API_KEY = "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"

def test_groq_simple():
    print("🔍 Простейший тест Groq...")
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "user", "content": "Say hello"}
        ],
        "max_tokens": 10
    }
    
    try:
        # Используем обычный json.dumps без ensure_ascii
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=10
        )
        
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            print(f"✅ Успешно! Ответ: {text}")
            return True
        else:
            print(f"❌ Ошибка: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Исключение: {e}")
        return False

if __name__ == "__main__":
    test_groq_simple()