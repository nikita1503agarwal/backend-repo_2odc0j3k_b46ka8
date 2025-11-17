from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Supplier
class SupplierBase(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class SupplierCreate(SupplierBase):
    pass

class SupplierRead(SupplierBase):
    id: int
    class Config:
        from_attributes = True

# Category
class CategoryBase(BaseModel):
    name: str

class CategoryCreate(CategoryBase):
    pass

class CategoryRead(CategoryBase):
    id: int
    class Config:
        from_attributes = True

# Product
class ProductBase(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    price: float = Field(ge=0, default=0)
    cost: float = Field(ge=0, default=0)
    quantity: int = 0
    reorder_level: int = 0
    is_active: bool = True
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    quantity: Optional[int] = None
    reorder_level: Optional[int] = None
    is_active: Optional[bool] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None

class ProductRead(ProductBase):
    id: int
    class Config:
        from_attributes = True

# Inventory Movement
class MovementBase(BaseModel):
    product_id: int
    change: int
    reason: str
    reference: Optional[str] = None

class MovementCreate(MovementBase):
    pass

class MovementRead(MovementBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True
