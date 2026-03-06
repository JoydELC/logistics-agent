"""
Modelos Pydantic para tickets de incidencias.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

IssueType = Literal["damage", "delay", "loss", "other"]
SeverityType = Literal["low", "medium", "high"]

# Regex básicos para validación cuando se proporcionan email o teléfono
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_REGEX = re.compile(r"^[\d\s\-\+\(\)]{7,20}$")


class ContactInfo(BaseModel):
    """
    Información de contacto asociada a un ticket.
    """

    name: str = Field(..., description="Nombre del contacto")
    phone: str = Field(default="", description="Teléfono (opcional)")
    email: str = Field(default="", description="Email (opcional)")

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        if v and not EMAIL_REGEX.match(v.strip()):
            raise ValueError("Formato de email no válido")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str) -> str:
        if v and not PHONE_REGEX.match(v.strip()):
            raise ValueError(
                "Formato de teléfono no válido (7-20 caracteres: dígitos, espacios, +, -, paréntesis)"
            )
        return v


class TicketCreate(BaseModel):
    """
    Body para crear un ticket de incidencia.
    """

    shipment_id: str = Field(..., description="ID del envío relacionado")
    issue_type: IssueType = Field(
        ...,
        description="Tipo de incidencia: damage, delay, loss u other",
    )
    description: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Descripción del problema (entre 5 y 500 caracteres)",
    )
    severity: SeverityType = Field(
        ...,
        description="Severidad: low, medium o high",
    )
    contact: ContactInfo = Field(..., description="Datos de contacto")


class TicketResponse(BaseModel):
    """
    Respuesta con el ticket creado o consultado.
    """

    ticket_id: str = Field(..., description="ID del ticket (UUID corto generado)")
    shipment_id: str = Field(..., description="ID del envío relacionado")
    issue_type: str = Field(..., description="Tipo de incidencia")
    description: str = Field(..., description="Descripción del problema")
    severity: str = Field(..., description="Severidad")
    contact: ContactInfo = Field(..., description="Datos de contacto")
    created_at: str = Field(..., description="Fecha de creación (ISO timestamp)")
    status: str = Field(default="open", description="Estado del ticket")
