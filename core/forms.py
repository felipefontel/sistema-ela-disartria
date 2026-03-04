from django import forms
from .models import Patient

class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ['name', 'birth_date', 'gender', 'diagnosis', 'diagnosis_other', 'consent_signed']
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'diagnosis': forms.Select(attrs={'class': 'form-control', 'id': 'id_diagnosis'}),
            'diagnosis_other': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_diagnosis_other', 'style': 'display:none;'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        diagnosis = cleaned_data.get('diagnosis')
        diagnosis_other = cleaned_data.get('diagnosis_other')
        consent_signed = cleaned_data.get('consent_signed')

        if diagnosis == 'OUTRO' and not diagnosis_other:
            self.add_error('diagnosis_other', 'Por favor, especifique o diagnóstico.')
        elif diagnosis != 'OUTRO':
            cleaned_data['diagnosis_other'] = ''

        if not consent_signed:
            self.add_error('consent_signed', 'Deve confirmar o Termo de Consentimento Livre e Esclarecido (TCLE) para prosseguir.')

        return cleaned_data
