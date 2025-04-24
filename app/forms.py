from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email

class LoginForm(FlaskForm):
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember me')
    submit = SubmitField('Login')

from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


class RegistrationForm(FlaskForm):
    firstname = StringField('First Name', validators=[DataRequired(), Length(min=1, max=50)])
    lastname = StringField('Last Name', validators=[DataRequired(), Length(min=1, max=50)])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    address = TextAreaField('Address', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField(
        'Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    terms = BooleanField('I agree', validators=[DataRequired(message='You must agree to the terms and conditions.')])
    submit = SubmitField('Create Account')

   