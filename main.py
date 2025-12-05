from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from gradio_client import Client as GradioClient, handle_file
from pydantic import BaseModel
from typing import Optional  # ✅ تمت إضافتها للتعامل مع الحقول الاختيارية
import shutil
import os
import json
import ast
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
# تأكد أن ملف .env يحتوي على SUPABASE_KEY (service_role)
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

# إنشاء عميل Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ✅ الربط مع موديل Monkeypox الجديد
hf_client = GradioClient("m-taha6/monkeypox")

# ---------------------------------------------------------
# 3. قاعدة البيانات الطبية (Medical Knowledge Base)
# ---------------------------------------------------------
MEDICAL_REPORT_DATA = {
    "Monkeypox": {
        "assessment": "The analysis indicates signs consistent with Monkeypox. Lesions typically progress from macules to papules, vesicles, pustules, and then scabs.",
        "key_features": [
            "Deep-seated, firm/hard lesions",
            "Well-defined borders with central umbilication",
            "Lesions often start on the face/mouth and spread",
            "Swollen lymph nodes (lymphadenopathy)"
        ],
        "recommendations": [
            "Isolate immediately to prevent spread.",
            "Wear a mask and cover lesions.",
            "Consult a healthcare provider for PCR testing.",
            "Monitor for fever and other systemic symptoms."
        ]
    },
    "Chickenpox": {
        "assessment": "The skin shows signs characteristic of Chickenpox (Varicella). This usually presents as an itchy, blister-like rash.",
        "key_features": [
            "Rash appears in crops (different stages visible)",
            "Superficial dew-drop on a rose petal appearance",
            "Intense itching",
            "Usually starts on the trunk and spreads"
        ],
        "recommendations": [
            "Stay at home until all blisters have crusted over.",
            "Use calamine lotion to soothe itching.",
            "Avoid scratching to prevent secondary infection.",
            "Avoid contact with pregnant women or immunocompromised individuals."
        ]
    },
    "Measles": {
        "assessment": "The analysis suggests Measles. This is a highly contagious viral infection appearing as a flat, red rash.",
        "key_features": [
            "Flat red rash starting at hairline/face",
            "Spreads downwards to neck, trunk, and limbs",
            "Associated with high fever, cough, and runny nose",
            "Tiny white spots inside the mouth (Koplik spots)"
        ],
        "recommendations": [
            "Seek medical attention immediately (highly contagious).",
            "Isolate from others, especially unvaccinated individuals.",
            "Rest and maintain hydration.",
            "Vitamin A supplements may be prescribed by a doctor."
        ]
    },
    "Normal": {
        "assessment": "The skin appears healthy with no signs of pathological rashes related to Monkeypox, Chickenpox, or Measles.",
        "key_features": [
            "Clear skin texture",
            "No suspicious lesions or blisters",
            "Normal pigmentation"
        ],
        "recommendations": [
            "Continue regular skin hygiene routine.",
            "Use sunscreen when exposed to the sun.",
            "Perform regular self-checks for any changes.",
            "Stay hydrated to maintain skin health."
        ]
    }
}

@app.get("/")
def home():
    return {"message": "Skin Disease Classification API is Running!"}

# =========================================================
# 4. الـ Scan Endpoint
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
        
        # استخدام api_name="/predict"
        result = hf_client.predict(
            image=handle_file(temp_filename),
            api_name="/predict" 
        )
        
        # ج) استخراج النتيجة (التشخيص)
        predicted_diagnosis = str(result)
        confidence = 0.95 

        try:
            # محاولة استخراج الليبل لو النتيجة JSON
            if isinstance(result, dict) and 'label' in result:
                predicted_diagnosis = result['label']
            elif isinstance(result, str) and "{'label':" in result:
                res_dict = ast.literal_eval(result)
                predicted_diagnosis = res_dict['label']
        except:
            pass 
            
        print(f"✅ Diagnosis Detected: {predicted_diagnosis}")

        # د) جلب التقرير الطبي المناسب
        report_data = MEDICAL_REPORT_DATA.get(predicted_diagnosis, {
            "assessment": "Analysis completed. Diagnosis not specifically listed.",
            "key_features": [],
            "recommendations": ["Consult a doctor for further checkup."]
        })

        # هـ) رفع الصورة لـ Supabase (البوكت الجديد)
        BUCKET_NAME = "skin-diseases"
        
        print(f"☁️ Uploading Image to {BUCKET_NAME}...")
        with open(temp_filename, "rb") as f:
            file_content = f.read()
        
        file_path = f"{user_id}/{file.filename}"
        
        # الرفع
        supabase.storage.from_(BUCKET_NAME).upload(file_path, file_content, {"upsert": "true"})
        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

        # و) حفظ البيانات في الهيستوري
        print("💾 Saving to History...")
        data = {
            "user_id": user_id,
            "image_url": public_url,
            "diagnosis": predicted_diagnosis,
            "confidence": float(confidence),
            "medical_advice": json.dumps(report_data) 
        }
        
        supabase.table("scan_history").insert(data).execute()

        # ز) تنظيف الملف المؤقت
        os.remove(temp_filename)

        # الرد النهائي
        return {
            "status": "success",
            "diagnosis": predicted_diagnosis,
            "image_url": public_url,
            "report": report_data 
        }

    except Exception as e:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return {"status": "error", "message": str(e)}

# =========================================================
# 5. إدارة البروفايل (Profile Management) - ✅ تم التحديث
# =========================================================
class ProfileUpdate(BaseModel):
    user_id: str
    full_name: Optional[str] = None
    username: Optional[str] = None
    website: Optional[str] = None
    # ✅ الحقول الجديدة لدعم التعديلات الطبية والشخصية
    age: Optional[int] = None
    gender: Optional[str] = None
    skin_type: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None 

@app.get("/profile/{user_id}")
def get_profile(user_id: str):
    try:
        # select("*") ستجلب جميع الحقول الجديدة تلقائياً
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        if not response.data:
            return {"status": "error", "message": "Profile not found"}
        return {"status": "success", "data": response.data[0]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.put("/profile/update")
def update_profile(profile: ProfileUpdate):
    try:
        # ✅ تصفية البيانات: نأخذ فقط القيم التي تم إرسالها (ليست None)
        # هذا يمنع مسح البيانات القديمة إذا لم يرسلها المستخدم
        data_to_update = {k: v for k, v in profile.dict().items() if v is not None and k != "user_id"}
        
        if not data_to_update:
            return {"status": "error", "message": "No data to update"}

        print(f"🔄 Updating Profile for {profile.user_id}: {data_to_update}")

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
        # ترتيب النتائج من الأحدث للأقدم
        response = supabase.table("scan_history").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        
        final_data = []
        for item in response.data:
            # تحويل النص لـ JSON في حالة medical_advice
            if item.get("medical_advice"):
                try:
                    item["medical_advice"] = json.loads(item["medical_advice"])
                except:
                    pass
            final_data.append(item)
            
        return {"status": "success", "data": final_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

