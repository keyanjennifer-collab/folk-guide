"""正式商城商品目录。

第一期开售商品较少，目录随代码发布，库存单独存入数据库。所有订单金额都在服务端
根据这里的分价重新计算，客户端上传的名称和金额一律不采信。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogProduct:
    id: str
    name: str
    price_fen: int
    category: str
    weight_grams: int
    active: bool = True


PRODUCTS: tuple[CatalogProduct, ...] = (
    CatalogProduct("gift", "五色知时线香套装", 23900, "set", 1200),
    CatalogProduct("green", "青木", 5900, "single", 260),
    CatalogProduct("red", "朱蜜", 5900, "single", 260),
    CatalogProduct("gold", "黄檀", 5900, "single", 260),
    CatalogProduct("white", "白桂", 5900, "single", 260),
    CatalogProduct("black", "墨沉", 5900, "single", 260),
)

PRODUCT_BY_ID = {product.id: product for product in PRODUCTS}


def product_or_none(product_id: str) -> CatalogProduct | None:
    return PRODUCT_BY_ID.get(product_id)
