from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from gradio_client import Client as GradioClient, handle_file
from pydantic import BaseModel
import shutil
import os
import json
import ast
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

app = FastAPI()

# ---------------------------------------------------------
# 1. تفعيل CORS
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 2. الإعدادات (من ملف .env)
# ---------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ Supabase keys are missing! Check .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
hf_client = GradioClient("m-taha6/acne-detection-api")

# ---------------------------------------------------------
# 3. قاعدة البيانات الطبية الثابتة (Medical Knowledge Base) 🏥
# ---------------------------------------------------------
MEDICAL_REPORT_DATA = {
    "Mild": {
        "assessment": "The skin shows signs of Mild Acne. This is characterized by whiteheads and blackheads. Inflammation is generally low.",
        "key_features": [
            "Presence of comedones",
            "Minimal inflammation",
            "No painful nodules"
        ],
        "recommendations": [
            "Wash face twice a day with a gentle cleanser.",
            "Avoid scrubbing your skin harshly.",
            "Use non-comedogenic skincare products."
        ]
    },
    "Moderate": {
        "assessment": "The analysis indicates Moderate Acne. Papules (red bumps) and pustules are visible. There is noticeable redness.",
        "key_features": [
            "Visible red papules",
            "Pustules with white centers",
            "Moderate redness"
        ],
        "recommendations": [
            "Consider over-the-counter benzoyl peroxide.",
            "Don't pop or squeeze pimples.",
            "Consult a pharmacist."
        ]
    },
    "Severe": {
        "assessment": "The image displays symptoms consistent with Severe Acne. Numerous inflamed papules and pustules are present. Risk of scarring is higher.",
        "key_features": [
            "Numerous inflamed papules",
            "Significant redness and swelling",
            "Potential for deep-seated nodules"
        ],
        "recommendations": [
            "Consult a dermatologist immediately.",
            "Prescription medication may be needed.",
            "Avoid all skin irritants."
        ]
    },
    "Very_Severe": {
        "assessment": "Diagnosis indicates Very Severe (Cystic) Acne. Large, painful cysts are present deep under the skin.",
        "key_features": [
            "Large, painful cysts and nodules",
            "Widespread inflammation",
            "High risk of permanent scarring"
        ],
        "recommendations": [
            "Urgent dermatologist care is required.",
            "Systemic treatment is likely necessary.",
            "Do not attempt to treat at home."
        ]
    }
}

@app.get("/")
def home():
    return {"message": "Acne Detection API is Running with Medical Report System!"}

# =========================================================
# 4. الـ Scan Endpoint (مع التقرير الطبي)
# =========================================================
@app.post("/scan")
async def scan_face(user_id: str = Form(...), file: UploadFile = File(...)):
    temp_filename = f"temp_{file.filename}"
    
    try:
        # أ) حفظ الصورة مؤقتاً
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # ب) إرسال الصورة للموديل
        print("🤖 Analyzing Image...")
        result = hf_client.predict(
            image=handle_file(temp_filename),
            api_name="/predict_acne"
        )
        
        # ج) تنظيف النتيجة لاستخراج الدرجة فقط
        predicted_grade = str(result)
        confidence = 0.95 

        try:
            if isinstance(result, dict) and 'label' in result:
                predicted_grade = result['label']
            elif isinstance(result, str) and "{'label':" in result:
                res_dict = ast.literal_eval(result)
                predicted_grade = res_dict['label']
        except:
            pass # Keep it as string if parsing fails
            
        print(f"✅ Grade Detected: {predicted_grade}")

        # د) جلب التقرير الطبي من القاموس
        report_data = MEDICAL_REPORT_DATA.get(predicted_grade, MEDICAL_REPORT_DATA["Mild"])

        # هـ) رفع الصورة لـ Supabase
        print("☁️ Uploading Image...")
        with open(temp_filename, "rb") as f:
            file_content = f.read()
        
        file_path = f"{user_id}/{file.filename}"
        supabase.storage.from_("acne-images").upload(file_path, file_content, {"upsert": "true"})
        public_url = supabase.storage.from_("acne-images").get_public_url(file_path)

        # و) حفظ البيانات في الهيستوري
        print("💾 Saving to History...")
        data = {
            "user_id": user_id,
            "image_url": public_url,
            "acne_grade": predicted_grade,
            "confidence": float(confidence),
            # بنحول التقرير لنص عشان يتحفظ في عمود text في الداتابيز
            "medical_advice": json.dumps(report_data) 
        }
        
        supabase.table("scan_history").insert(data).execute()

        # ز) تنظيف الملف المؤقت
        os.remove(temp_filename)

        # الرد النهائي للفرونت اند
        return {
            "status": "success",
            "grade": predicted_grade,
            "image_url": public_url,
            "report": report_data 
        }

    except Exception as e:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return {"status": "error", "message": str(e)}

# =========================================================
# 5. إدارة البروفايل (Profile Management)
# =========================================================
class ProfileUpdate(BaseModel):
    user_id: str
    full_name: str = None
    username: str = None
    website: str = None

@app.get("/profile/{user_id}")
def get_profile(user_id: str):
    try:
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        if not response.data:
            return {"status": "error", "message": "Profile not found"}
        return {"status": "success", "data": response.data[0]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.put("/profile/update")
def update_profile(profile: ProfileUpdate):
    try:
        data_to_update = {}
        if profile.full_name: data_to_update["full_name"] = profile.full_name
        if profile.username: data_to_update["username"] = profile.username
        if profile.website: data_to_update["website"] = profile.website
        
        if not data_to_update:
            return {"status": "error", "message": "No data to update"}

        response = supabase.table("profiles").update(data_to_update).eq("id", profile.user_id).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# =========================================================
# 6. جلب الهيستوري (History)
# =========================================================
@app.get("/history/{user_id}")
def get_user_history(user_id: str):
    try:
        response = supabase.table("scan_history").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        
        # تحويل النص المحفوظ في medical_advice لـ JSON مرة تانية عشان الفرونت اند يفهمه
        final_data = []
        for item in response.data:
            if item.get("medical_advice"):
                try:
                    item["medical_advice"] = json.loads(item["medical_advice"])
                except:
                    pass
            final_data.append(item)
            
        return {"status": "success", "data": final_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}