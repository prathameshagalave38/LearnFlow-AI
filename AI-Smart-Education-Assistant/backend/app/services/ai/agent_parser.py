import json
import logging
import re
from typing import Dict, Any
from groq import AsyncGroq
from app.core.config import settings

logger = logging.getLogger(__name__)

class SympraAgentParser:
    def __init__(self):
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.models_to_try = [
            "openai/gpt-oss-20b",
            "groq/compound",
            "qwen/qwen3.6-27b",
            "llama-3.3-70b-versatile",
            "groq/compound-mini"
        ]

    async def parse_intent(self, transcript: str, current_page: str) -> Dict[str, Any]:
        system_prompt = """
        You are the 'Sympra Voice Agent Brain'. 
        The user has spoken a command.
        You must analyze the command and extract the intent and target parameters.
        
        Supported Intents:
        - CHAT: User wants to ask a question to the AI chat.
        - GENERATE_NOTES: User wants to generate notes from a document or topic.
        - GENERATE_MINDMAP: User wants to generate a mind map (e.g., "mind map", "mindmap").
        - AI_TEACHER_TEST: User wants to start a test/quiz with the AI Teacher.
        - GENERATE_QUIZ: User wants to generate a quiz.
        - GENERATE_FLASHCARDS: User wants to generate flashcards.
        - UNKNOWN: The intent is not recognized.

        Language Instructions:
        - YOU MUST ALWAYS set "detected_language" to "en" and your "speech_reply" MUST be in pure English language, regardless of what language the user speaks.
        - The user will often speak in Marathi or Hindi mixed with English (e.g. "mala quiz generate kar", "flashcards banav", "mind map dakhava", "mala test ghya").
        - Map these precisely! If they say "quiz" -> GENERATE_QUIZ. If they say "flashcards" -> GENERATE_FLASHCARDS. If they say "notes" -> GENERATE_NOTES. If they say "test" or "test ghya" -> AI_TEACHER_TEST.
        - Pay close attention to their NEWEST command. Do not stick to old tasks if they ask for a new feature.

        You MUST output your response STRICTLY as a JSON object matching this schema:
        {
            "detected_language": "en",
            "intent": "CHAT" | "GENERATE_NOTES" | "GENERATE_MINDMAP" | "AI_TEACHER_TEST" | "GENERATE_QUIZ" | "GENERATE_FLASHCARDS" | "UNKNOWN",
            "parameters": {
                "source": "document" | "selected_document" | "topic" | null,
                "topic_name": "string or null",
                "chat_query": "string or null"
            },
            "speech_reply": "A brief, natural reply in English confirming the action."
        }
        
        Do NOT wrap the JSON in markdown blocks like ```json. Output ONLY the raw JSON object.
        """
        
        prompt = f"Current Page: {current_page}\nUser Transcript: \"{transcript}\""
        
        last_error = None
        for model in self.models_to_try:
            result_text = ""
            try:
                logger.info(f"Parsing intent with model {model} for transcript: '{transcript}'")
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1, 
                    response_format={"type": "json_object"}
                )
                
                result_text = response.choices[0].message.content or ""
                # Clean think tags if present
                if "</think>" in result_text:
                    result_text = result_text.split("</think>")[-1]
                result_text = re.sub(r'<think>[\s\S]*?$', '', result_text, flags=re.IGNORECASE)
                result_text = re.sub(r'<think>[\s\S]*?</think>', '', result_text, flags=re.IGNORECASE).strip()

                # Extract JSON object substring if model output contains preamble
                json_match = re.search(r'\{[\s\S]*\}', result_text)
                if json_match:
                    result_text = json_match.group(0)

                logger.info(f"LLM ({model}) Extracted JSON: {result_text}")
                return json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON Parsing Error with model {model}: {e} - Raw output: {result_text}")
                last_error = e
            except Exception as e:
                logger.warning(f"Groq API call for model {model} failed: {e}. Trying fallback model...")
                last_error = e

        logger.error(f"All models failed parsing intent: {last_error}")
        return {
            "detected_language": "en",
            "intent": "UNKNOWN",
            "parameters": {},
            "speech_reply": "I'm sorry, I couldn't understand that."
        }

agent_parser = SympraAgentParser()


