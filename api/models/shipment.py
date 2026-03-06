"""
Modelos Pydantic para envíos (shipments).
Basados en la estructura real de data/shipments.json.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# --- Validación de formatos ---
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_WINDOW_REGEX = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")


class FaxDetail(BaseModel):
    """
    Detalle del fax asociado a un envío.
    Corresponde al objeto "fax" en el JSON. Todos los campos admiten vacío.
    """

    model_config = {"extra": "forbid"}

    order_type: str = Field(default="", description='Tipo de orden: "PU", "DE" o "CT"')
    customer_code: str = Field(default="", description="Código del cliente")
    invoice: str = Field(default="", description="Número de factura")
    container_letters: str = Field(default="", description="Letras del contenedor")
    container_numbers: str = Field(default="", description="Números del contenedor")
    fordriver: str = Field(default="", description="Identificador para el conductor")

    stop1_name: str = Field(default="", description="Nombre parada 1")
    stop1_add: str = Field(default="", description="Dirección parada 1")
    stop1_city: str = Field(default="", description="Ciudad parada 1")
    stop1_st: str = Field(default="", description="Estado parada 1")
    stop1_zip: str = Field(default="", description="Zip parada 1")

    stop2_name: str = Field(default="", description="Nombre parada 2")
    stop2_add: str = Field(default="", description="Dirección parada 2")
    stop2_city: str = Field(default="", description="Ciudad parada 2")
    stop2_st: str = Field(default="", description="Estado parada 2")
    stop2_zip: str = Field(default="", description="Zip parada 2")

    stop3_name: str = Field(default="", description="Nombre parada 3 (opcional)")
    stop3_add: str = Field(default="", description="Dirección parada 3")
    stop3_city: str = Field(default="", description="Ciudad parada 3")
    stop3_st: str = Field(default="", description="Estado parada 3")
    stop3_zip: str = Field(default="", description="Zip parada 3")
    date3: str = Field(default="", description="Fecha parada 3 (YYYY-MM-DD o vacío)")
    time3: str = Field(default="", description="Hora parada 3 (HH:MM o vacío)")

    stop4_name: str = Field(default="", description="Nombre parada 4 (opcional)")
    stop4_add: str = Field(default="", description="Dirección parada 4")
    stop4_city: str = Field(default="", description="Ciudad parada 4")
    stop4_st: str = Field(default="", description="Estado parada 4")
    stop4_zip: str = Field(default="", description="Zip parada 4")
    date4: str = Field(default="", description="Fecha parada 4 (YYYY-MM-DD o vacío)")
    time4: str = Field(default="", description="Hora parada 4 (HH:MM o vacío)")

    date1: str = Field(default="", description="Fecha 1 (YYYY-MM-DD o vacío)")
    date2: str = Field(default="", description="Fecha 2 (YYYY-MM-DD o vacío)")
    time1: str = Field(default="", description="Hora 1 (HH:MM o vacío)")
    time2: str = Field(default="", description="Hora 2 (HH:MM o vacío)")

    droploaded: str = Field(default="", description="Drop/loaded")
    rate: str = Field(default="", description="Tarifa")
    fuelsurcharge: str = Field(default="", description="Recargo combustible")
    multistop: str = Field(default="", description="Multiparada")
    pieces: str = Field(default="", description="Piezas")
    weight: str = Field(default="", description="Peso")

    blbk: str = Field(default="", description="BL/BK")
    seal: str = Field(default="", description="Sello")
    RefRail: str = Field(default="", description="Referencia ferrocarril")
    refcom: str = Field(default="", description="Referencia com")

    addicionalrate1: str = Field(default="", description="Tarifa adicional 1")
    addicionalvalue1: str = Field(default="", description="Valor adicional 1")
    addicionalrate2: str = Field(default="", description="Tarifa adicional 2")
    addicionalvalue2: str = Field(default="", description="Valor adicional 2")
    addicionalrate3: str = Field(default="", description="Tarifa adicional 3")
    addicionalvalue3: str = Field(default="", description="Valor adicional 3")
    addicionalrate4: str = Field(default="", description="Tarifa adicional 4")
    addicionalvalue4: str = Field(default="", description="Valor adicional 4")

    BOL: str = Field(default="", description="BOL")
    COM1: str = Field(default="", description="Comentario 1")
    COM2: str = Field(default="", description="Comentario 2")

    rampfilter1: str = Field(default="", description="Filtro rampa 1 (opcional)")
    rampfilter2: str = Field(default="", description="Filtro rampa 2 (opcional)")


class ShipmentRecord(BaseModel):
    """
    Registro completo de un envío tal como aparece en el JSON.
    No incluye _id de MongoDB.
    """

    model_config = {"extra": "forbid"}

    shipmentid: str = Field(..., description="Identificador del envío")
    hour_init: str = Field(..., description="Hora de inicio")
    hour_end: str = Field(..., description="Hora de fin")
    fax: FaxDetail = Field(..., description="Detalle del fax del envío")


class ShipmentResponse(BaseModel):
    """
    Respuesta de GET /shipments/{id}.
    Incluye el registro completo más campos calculados.
    """

    model_config = {"extra": "forbid"}

    shipmentid: str = Field(..., description="Identificador del envío")
    hour_init: str = Field(..., description="Hora de inicio")
    hour_end: str = Field(..., description="Hora de fin")
    fax: FaxDetail = Field(..., description="Detalle del fax del envío")
    derived_status: str = Field(
        ..., description="Estado derivado (calculado, no viene del JSON)"
    )
    eta_info: Optional[str] = Field(default=None, description="Información ETA opcional")


class RescheduleRequest(BaseModel):
    """
    Body del POST de reprogramación de envío.
    """

    new_date: str = Field(..., description="Nueva fecha en formato YYYY-MM-DD")
    new_time_window: str = Field(
        ...,
        description='Ventana horaria: "mañana", "tarde", "noche" o formato "HH:MM-HH:MM"',
    )
    note: Optional[str] = Field(default="", description="Nota opcional")

    @field_validator("new_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if v and not DATE_REGEX.match(v):
            raise ValueError("new_date debe tener formato YYYY-MM-DD")
        return v

    @field_validator("new_time_window")
    @classmethod
    def validate_time_window(cls, v: str) -> str:
        allowed = {"mañana", "tarde", "noche"}
        if v in allowed:
            return v
        if v and not TIME_WINDOW_REGEX.match(v):
            raise ValueError(
                'new_time_window debe ser "mañana", "tarde", "noche" o "HH:MM-HH:MM"'
            )
        return v


class RescheduleResponse(BaseModel):
    """
    Respuesta del POST de reprogramación.
    """

    success: bool = Field(..., description="Indica si la reprogramación fue exitosa")
    shipment_id: str = Field(..., description="ID del envío reprogramado")
    previous_date: Optional[str] = Field(default=None, description="Fecha anterior")
    new_date: str = Field(..., description="Nueva fecha asignada")
    new_time_window: str = Field(..., description="Nueva ventana horaria")
    message: str = Field(..., description="Mensaje de resultado")


class ShipmentListResponse(BaseModel):
    """
    Respuesta paginada de GET /shipments/ (listar envíos).
    """

    items: list[ShipmentResponse] = Field(..., description="Lista de envíos")
    total: int = Field(..., description="Total de registros (antes de limit/offset)")
