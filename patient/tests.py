from rest_framework.test import APITestCase

from .models import Doctor


class DoctorListApiTests(APITestCase):
	def test_lists_doctors(self):
		Doctor.objects.create(
			doctor_id="DOC001",
			name="Anjali Krishnan",
			specialty="Physical Medicine and Rehabilitation",
			email="anjali.krishnan@example.com",
		)

		response = self.client.get("/api/doctors/")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.data), 1)
		self.assertEqual(response.data[0]["doctor_id"], "DOC001")
		self.assertEqual(response.data[0]["name"], "Anjali Krishnan")
		self.assertEqual(response.data[0]["specialty"], "Physical Medicine and Rehabilitation")


class PatientProfileApiTests(APITestCase):
	def test_create_patient_with_measurements_and_doctor(self):
		doctor = Doctor.objects.create(doctor_id="DOC001", name="Anjali Krishnan")
		response = self.client.post(
			"/api/patients/",
			{
				"patient_id": "PAT001",
				"name": "Jane Doe",
				"doctor_id": doctor.doctor_id,
				"height_cm": "168.50",
				"weight_kg": "62.25",
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["doctor_id"], "DOC001")
		self.assertEqual(response.data["doctor_name"], "Anjali Krishnan")
		self.assertEqual(str(response.data["height_cm"]), "168.50")
		self.assertEqual(str(response.data["weight_kg"]), "62.25")
