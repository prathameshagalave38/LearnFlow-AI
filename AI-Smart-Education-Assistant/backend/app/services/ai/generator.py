import os, re
from typing import List, Dict
from groq import AsyncGroq
import base64

from app.core.config import settings

import logging
logger = logging.getLogger(__name__)

class AIGenerator:
    def __init__(self):
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.text_model = "groq/compound-mini"
        self.vision_model = "groq/compound-mini"

    async def _create_completion(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 2048, response_format: dict = None) -> str:
        models_to_try = ["qwen/qwen3.6-27b", "openai/gpt-oss-20b", "groq/compound-mini", "groq/compound"]
        last_error = None
        for model in models_to_try:
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                if response_format:
                    kwargs["response_format"] = response_format
                response = await self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                # Strip out <think>...</think> reasoning blocks if present
                if "</think>" in content:
                    content = content.split("</think>")[-1]
                content = re.sub(r'<think>[\s\S]*$', '', content, flags=re.IGNORECASE)
                content = re.sub(r'<think>[\s\S]*?</think>', '', content, flags=re.IGNORECASE).strip()
                return content
            except Exception as e:
                logger.warning(f"Groq API call with model {model} failed: {e}. Trying fallback model...")
                last_error = e
        
        # If all Groq models fail, raise last error
        raise last_error

    def _build_context_string(self, chunks: List[Dict]) -> str:
        context_str = ""
        for i, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            meta = chunk.get("metadata", {})
            doc_id = meta.get("document_id", "Unknown")
            context_str += f"--- Source {i+1} (Doc: {doc_id}) ---\n{content}\n\n"
        return context_str

    def _get_language_instruction(self, language: str) -> str:
        if not language or language.lower() == "english":
            return "Please respond entirely in English."
            
        return f"""
        CRITICAL INSTRUCTION: You MUST respond ONLY in {language}, using its native script (e.g., Devanagari for Marathi/Hindi). 
        Do NOT respond in English or any other language under any circumstance.
        Even if the user's question contains English words or technical terms — transliterate or translate technical terms into {language} where natural, otherwise keep the exact term but write the surrounding sentence entirely in {language}.
        If you fail to write the response in {language}, it is a critical failure.
        """

    async def generate_chat_response(
        self, 
        query: str, 
        context_chunks: List[Dict], 
        chat_history: List[Dict] = None,
        language: str = "English",
        images: List[str] = None,
        doc_names: List[str] = None
    ) -> str:
        context_str = self._build_context_string(context_chunks)
        
        doc_info = f"The student has selected the following documents: {', '.join(doc_names)}\n" if doc_names else ""
        system_prompt = f"""
        You are an intelligent educational assistant. {doc_info}
        Use the following extracted context from study materials to answer the student's question if relevant.
        If the student asks to explain or summarize the selected document(s), use your general knowledge about the document's topic along with any provided context to explain it.
        If the context is empty, missing, or irrelevant to the question, act as a helpful AI assistant and answer the question directly using your general knowledge. Do NOT complain about missing context.
        Always cite the source document name if you do use context.
        
        {self._get_language_instruction(language)}

        Context:
        {context_str}
        """

        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role not in ["system", "user", "assistant"]:
                    role = "user"
                messages.append({"role": role, "content": content})

        if images and len(images) > 0:
            content = [{"type": "text", "text": query}]
            if language and language.lower() != "english":
                content[0]["text"] += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
            for img_b64 in images:
                if "," in img_b64:
                    img_b64 = img_b64.split(",")[1]
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                })
            messages.append({"role": "user", "content": content})
            model_to_use = self.vision_model
        else:
            final_query = query
            if language and language.lower() != "english":
                final_query += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
        messages.append({"role": "user", "content": final_query})
        return await self._create_completion(messages, temperature=0.7, max_tokens=1024)

    async def generate_chat_stream(
        self, 
        query: str, 
        context_chunks: List[Dict], 
        chat_history: List[Dict] = None,
        language: str = "English",
        images: List[str] = None,
        doc_names: List[str] = None
    ):
        context_str = self._build_context_string(context_chunks)
        
        doc_info = f"The student has selected the following documents: {', '.join(doc_names)}\n" if doc_names else ""
        system_prompt = f"""
        You are an intelligent educational assistant. {doc_info}
        Use the following extracted context from study materials to answer the student's question if relevant.
        If the student asks to explain or summarize the selected document(s), use your general knowledge about the document's topic along with any provided context to explain it.
        If the context is empty, missing, or irrelevant to the question, act as a helpful AI assistant and answer the question directly using your general knowledge. Do NOT complain about missing context.
        Always cite the source document name if you do use context.
        
        {self._get_language_instruction(language)}

        Context:
        {context_str}
        """

        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role not in ["system", "user", "assistant"]:
                    role = "user"
                messages.append({"role": role, "content": content})

        if images and len(images) > 0:
            content = [{"type": "text", "text": query}]
            if language and language.lower() != "english":
                content[0]["text"] += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
            for img_b64 in images:
                if "," in img_b64:
                    img_b64 = img_b64.split(",")[1]
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                })
            messages.append({"role": "user", "content": content})
            model_to_use = self.vision_model
        else:
            final_query = query
            if language and language.lower() != "english":
                final_query += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
            messages.append({"role": "user", "content": final_query})
            model_to_use = self.text_model
        
        try:
            stream = await self.client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                stream=True
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.warn(f"Stream failed with {model_to_use}: {e}. Falling back to non-stream completion.")
            text = await self._create_completion(messages, temperature=0.7, max_tokens=1024)
            yield text

    async def generate_quiz(self, context_chunks: List[Dict], difficulty: str = "Medium", num_questions: int = 5) -> str:
        context_str = self._build_context_string(context_chunks)
        
        prompt = f"""
        You are a teacher. Create a {difficulty} difficulty quiz with EXACTLY {num_questions} multiple-choice questions based on the study materials below (or topic knowledge if context is sparse).
        
        CRITICAL OUTPUT REQUIREMENTS:
        1. Output MUST be a JSON array containing EXACTLY {num_questions} objects.
        2. Each object MUST have:
           - "question": string (the question text)
           - "options": array of EXACTLY 4 strings (e.g. ["Option A text", "Option B text", "Option C text", "Option D text"])
           - "answer": string (must match ONE of the option strings exactly or be the correct index/letter)
           - "explanation": string (detailed explanation of why the correct answer is right)
        3. Do NOT output any conversational text or markdown wrap like ```json. Return ONLY valid JSON array.

        Context:
        {context_str}
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.6, max_tokens=3000)

    async def generate_flashcards(self, context_chunks: List[Dict], num_flashcards: int = 5) -> str:
        context_str = self._build_context_string(context_chunks)
        
        prompt = f"""
        Create EXACTLY {num_flashcards} flashcards from the provided study material.
        Output MUST be a JSON object containing a "flashcards" array.
        Each item in the "flashcards" array MUST include ALL of these fields:
        - "question": string (the prompt or question for the front of the card)
        - "front": string (same value as question)
        - "answer": string (the comprehensive answer for the back of the card)
        - "back": string (same value as answer)
        - "difficulty": string ("Easy", "Medium", or "Hard")
        - "subject": string (identify the main subject or subtopic)
        
        Return ONLY valid JSON. Do not wrap in markdown fences.

        Context:
        {context_str}
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.7, max_tokens=3000, response_format={"type": "json_object"})
        
    async def generate_study_plan(self, topics: str, days: int, hours_per_day: int) -> str:
        prompt = f"""
        Create a detailed study plan for a student who needs to study the following topics: {topics}.
        They have {days} days until the exam, and can study {hours_per_day} hours per day.
        Provide a day-by-day structured plan.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.7, max_tokens=2000)

    async def generate_notes(self, context_chunks: List[Dict], note_type: str = "Summary Notes") -> str:
        context_str = self._build_context_string(context_chunks)
        
        prompt = f"""
        Generate high-quality, beautifully formatted Markdown notes of type "{note_type}" from the provided study material.

        CRITICAL STYLING & DEPTH INSTRUCTIONS BASED ON NOTE TYPE:
        - If "Short Notes": Provide concise, bulleted summary notes (15 to 20 key bullet points). Group under 3-4 clear subheadings. Keep each point brief for quick revision.
        - If "Detailed Notes": Provide COMPREHENSIVE, IN-DEPTH, EXTENSIVE study notes (approx 600-1200 words). Include:
            1. Executive Summary & Core Context
            2. Detailed Section-by-Section Explanations with deep breakdowns of theoretical concepts
            3. Concrete Examples, Code Snippets, or Step-by-Step Problem Solving where applicable
            4. Key Definitions & Formulas Table
            5. Critical Exam Tips & Common Pitfalls
            6. Summary Review Checklist
        - If "Chapter Summary": Provide an overarching executive summary explaining the main narrative, core themes, structural components, and major outcomes.
        - If "Formula & Key Points": Extract ALL mathematical/scientific formulas, equations, constant values, laws, and foundational definitions into structured tables and callouts.

        Use Markdown headers (##, ###), bold text, bullet points, blockquotes for tips, and standard math syntax.

        Context:
        {context_str}
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.7, max_tokens=4000)

    async def generate_notes_for_topic(self, topic: str, note_type: str = "Summary Notes") -> str:
        prompt = f"""
        Generate high-quality, beautifully formatted Markdown notes of type "{note_type}" on the topic "{topic}".

        CRITICAL STYLING & DEPTH INSTRUCTIONS BASED ON NOTE TYPE:
        - If "Short Notes": Provide concise, bulleted summary notes (15 to 20 key bullet points). Group under 3-4 clear subheadings. Keep each point brief for quick revision.
        - If "Detailed Notes": Provide COMPREHENSIVE, IN-DEPTH, EXTENSIVE study notes (approx 600-1200 words). Include:
            1. Executive Summary & Core Context
            2. Detailed Section-by-Section Explanations with deep breakdowns of theoretical concepts
            3. Concrete Examples, Code Snippets, or Step-by-Step Problem Solving where applicable
            4. Key Definitions & Formulas Table
            5. Critical Exam Tips & Common Pitfalls
            6. Summary Review Checklist
        - If "Chapter Summary": Provide an overarching executive summary explaining the main narrative, core themes, structural components, and major outcomes.
        - If "Formula & Key Points": Extract ALL mathematical/scientific formulas, equations, constant values, laws, and foundational definitions into structured tables and callouts.

        Use Markdown headers (##, ###), bold text, bullet points, blockquotes for tips, and standard math syntax.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.7, max_tokens=4000)

    async def generate_mindmap(self, context_chunks: List[Dict], topic_name: str = None) -> str:
        context_str = self._build_context_string(context_chunks)
        topic_info = f"Topic / Document Title: {topic_name}\n" if topic_name else ""
        
        prompt = f"""
        Analyze the following study material and generate an interactive mind map structure.
        {topic_info}
        Identify the main topic, key subtopics, and their detailed child concepts based directly on the study material.
        
        OUTPUT REQUIREMENT:
        Output MUST be a valid JSON object with two top-level arrays: "nodes" and "edges".
        
        Nodes schema:
        - "id": unique string (e.g. "1", "2", "3", "4", "5", "6", "7")
        - "position": object with x and y coordinates (e.g. {{ "x": 400, "y": 50 }})
        - "data": object with label (e.g. {{ "label": "Main Topic" }})
        - "style": object for styling (e.g. {{ "background": "#3B82F6", "color": "white", "padding": 12, "borderRadius": 10, "fontWeight": "bold" }})
        
        Edges schema:
        - "id": string (e.g. "e1-2")
        - "source": string (id of source node)
        - "target": string (id of target node)
        - "animated": boolean (true)

        Layout Guidelines:
        - Root node (id: "1") at position {{ "x": 400, "y": 50 }} with background "#3B82F6"
        - Main subtopics at y: 180 (e.g. x: 150, 400, 650) with background "#8B5CF6", "#10B981", "#F59E0B"
        - Child subtopics at y: 300 (e.g. x: 80, 250, 400, 550, 720) with background "#64748B"
        
        IMPORTANT: All node labels MUST be directly related to the provided study material and topic ({topic_name or 'Uploaded Document'}).
        Do NOT output markdown fences. Return ONLY the raw JSON object.

        Context:
        {context_str}
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._create_completion(messages, temperature=0.6, max_tokens=3000, response_format={"type": "json_object"})

    async def generate_teacher_response(self, query: str, context_chunks: List[Dict], mode: str = "Beginner", chat_history: List[Dict] = None, language: str = "English") -> str:
        context_str = self._build_context_string(context_chunks)
        
        mode_instruction = ""
        if mode.lower() == "beginner":
            mode_instruction = "Explain concepts very simply, as if to a beginner. Use simple analogies and break down complex ideas step-by-step."
        elif mode.lower() == "advanced":
            mode_instruction = "Explain concepts in an advanced, detailed manner, suitable for an expert or higher-level student. Compare related concepts."
        else:
            mode_instruction = "Explain step-by-step and provide clear examples like a supportive teacher."

        system_prompt = f"""
        You are an expert Teacher. {mode_instruction}
        Use the following extracted context from study materials to answer the student's question.
        If the answer is not in the context, inform the student gently, but provide a helpful answer mentioning uncertainty.

        {self._get_language_instruction(language)}

        Context:
        {context_str}
        """
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role not in ["system", "user", "assistant"]:
                    role = "user"
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": query})
        return await self._create_completion(messages, temperature=0.7, max_tokens=2048)

    async def generate_mock_test_question(self, context_chunks: List[Dict], language: str = "English", history: List[Dict] = None) -> str:
        context_str = self._build_context_string(context_chunks)
        
        system_prompt = f"""
        You are a friendly, expert Exam Teacher conducting a 1-on-1 oral Mock Test with a student.
        Your sole task is to ask the student ONE 2-to-3 sentence exam question based directly on their uploaded study material.

        INSTRUCTIONS:
        1. Ask EXACTLY ONE conceptual exam question (2 to 3 sentences long) from the provided Study Material Context.
        2. Speak directly to the student asking them to explain or describe the concept.
        3. Do NOT answer the question yourself, do NOT write "Answer:", and do NOT write explanations.
        4. Do NOT output internal thoughts or <think> tags.
        
        {self._get_language_instruction(language)}

        Study Material Context:
        {context_str}
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            if language and language.lower() != "english" and messages[-1]["role"] == "user":
                messages[-1]["content"] += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
        else:
            msg_content = "Hello Teacher! Please ask me my first mock test question based on my uploaded study material."
            if language and language.lower() != "english":
                msg_content += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
            messages.append({"role": "user", "content": msg_content})

        raw_q = await self._create_completion(messages, temperature=0.7, max_tokens=400)
        cleaned = re.sub(r'^(Answer|Response|Explanation):\s*', '', raw_q, flags=re.IGNORECASE).strip()
        return cleaned

    async def evaluate_mock_test_answer(self, user_answer: str, context_chunks: List[Dict], language: str = "English", history: List[Dict] = None) -> str:
        context_str = self._build_context_string(context_chunks)
        
        system_prompt = f"""
        You are a supportive, expert AI Teacher conducting an interactive Mock Test with a student.
        The student is attempting a test question based on their study material.

        CRITICAL INSTRUCTIONS FOR RESPONDING TO THE STUDENT:

        CASE 1: THE STUDENT ASKS FOR AN EXPLANATION, CLARIFICATION, OR HELP
        If the student's message asks to explain the question/concept, asks for help, or says phrases like:
        - "explain this to me", "he mala explain kar", "mala samjhav", "mala explain kar", "please explain"
        - "explain question", "I don't understand", "tell me the answer", "explain", "help", "samjhav"
        - or asks any explanatory question about the current concept:
        --> DO NOT jump to the next question! Do NOT mark it wrong!
        --> Provide a clear, educational, step-by-step EXPLANATION of the current concept/question using the Study Material Context.
        --> End by asking the student if the explanation was clear and if they are ready to attempt answering or move to the next question.

        CASE 2: THE STUDENT ASKS FOR A HINT ("give me a hint", "hint", "mala hint de")
        --> Give a helpful, subtle hint about the concept without giving away the complete answer.

        CASE 3: THE STUDENT ANSWERS THE QUESTION
        If the student provides an answer to the exam question:
        --> Evaluate their answer in 1-2 encouraging sentences (indicate whether it is correct, partially correct, or incorrect, with brief constructive feedback).
        --> If the answer was incorrect or partial, briefly give the correct key points.
        --> Then, ask the NEXT conceptual exam question (2 to 3 sentences long) based on the Study Material Context.

        CASE 4: THE STUDENT ASKS FOR THE NEXT QUESTION ("next question", "pudhil prashna", "skip")
        --> Acknowledge smoothly and ask the NEXT conceptual exam question based on the Study Material Context.

        GENERAL RULES:
        - Maintain a warm, encouraging, expert teacher tone.
        - Do NOT output internal thoughts or <think> tags.
        
        {self._get_language_instruction(language)}

        Study Material Context:
        {context_str}
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                
        user_msg = user_answer
        if language and language.lower() != "english":
            user_msg += f"\n\n[CRITICAL REMINDER: You MUST respond ENTIRELY in {language} in Devanagari script. Do NOT use English sentences.]"
        messages.append({"role": "user", "content": user_msg})

        return await self._create_completion(messages, temperature=0.7, max_tokens=2048)

ai_generator = AIGenerator()
