from django import forms
from django.contrib.auth.models import User
from .models import Patient

class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ['name', 'birth_date', 'gender', 'phone', 'city', 'state', 'has_escort', 'escort_name', 'diagnosis', 'diagnosis_other', 'alsfrs_bulbar', 'consent_signed']
        widgets = {
            'birth_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(11) 98888-7777'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UF', 'maxlength': '2'}),
            'has_escort': forms.CheckboxInput(attrs={'id': 'id_has_escort'}),
            'escort_name': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_escort_name', 'style': 'display:none;'}),
            'diagnosis': forms.Select(attrs={'class': 'form-control', 'id': 'id_diagnosis'}),
            'diagnosis_other': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_diagnosis_other', 'style': 'display:none;'}),
            'alsfrs_bulbar': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '12'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        diagnosis = cleaned_data.get('diagnosis')
        diagnosis_other = cleaned_data.get('diagnosis_other')
        consent_signed = cleaned_data.get('consent_signed')
        has_escort = cleaned_data.get('has_escort')
        escort_name = cleaned_data.get('escort_name')

        if diagnosis == 'OUTRO' and not diagnosis_other:
            self.add_error('diagnosis_other', 'Por favor, especifique o diagnóstico.')
        elif diagnosis != 'OUTRO':
            cleaned_data['diagnosis_other'] = ''

        if has_escort and not escort_name:
            self.add_error('escort_name', 'Por favor, informe o nome do acompanhante.')
        elif not has_escort:
            cleaned_data['escort_name'] = ''

        if not consent_signed:
            self.add_error('consent_signed', 'Deve confirmar o Termo de Consentimento Livre e Esclarecido (TCLE) para prosseguir.')

        return cleaned_data


PAPEL_CHOICES = [
    ('medico', 'Médico'),
    ('admin', 'Administrador'),
]

class UserCreateForm(forms.Form):
    first_name = forms.CharField(label='Nome', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome'}))
    last_name = forms.CharField(label='Sobrenome', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sobrenome'}))
    username = forms.CharField(label='Usuário (login)', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'nome.usuario'}))
    email = forms.EmailField(label='E-mail', required=False, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}))
    papel = forms.ChoiceField(label='Papel', choices=PAPEL_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
    password = forms.CharField(label='Senha', widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha'}))
    password_confirm = forms.CharField(label='Confirmar Senha', widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirme a senha'}))

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Este nome de usuário já está em uso.')
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'As senhas não coincidem.')
        return cleaned_data


class UserEditForm(forms.Form):
    first_name = forms.CharField(label='Nome', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label='Sobrenome', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label='E-mail', required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    papel = forms.ChoiceField(label='Papel', choices=PAPEL_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
    password = forms.CharField(label='Nova Senha (deixe em branco para não alterar)', required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Nova senha (opcional)'}))
    password_confirm = forms.CharField(label='Confirmar Nova Senha', required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirme a nova senha'}))

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password != password_confirm:
            self.add_error('password_confirm', 'As senhas não coincidem.')
        return cleaned_data
