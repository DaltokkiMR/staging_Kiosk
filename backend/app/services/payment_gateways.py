"""결제사별 게이트웨이 어댑터.

결제수단마다 승인 방식이 모두 다르기 때문에 공통 인터페이스(PaymentGateway)로 감싸고,
서버는 이 인터페이스만 호출합니다. 지금은 해커톤 데모용 Mock 구현이며,
실제 연동 시 각 클래스의 charge() 안을 해당 사의 API 호출로 교체하면 됩니다.

  - 신용/체크카드, 삼성페이 : PG사(토스페이먼츠, KG이니시스, NICE 등) 빌링키 결제 API
  - 카카오페이              : 카카오페이 정기결제(SID) API
  - 네이버페이              : 네이버페이 자동결제 API
  - 지역화폐                : 지자체 지역화폐 운영사 API (예: 코나아이, 제로페이 연동)
  - 온누리상품권            : 모바일 온누리 결제 API
"""
import secrets
from dataclasses import dataclass

from ..models import PayType, PaymentMethod, Store


@dataclass
class GatewayResult:
    success: bool
    approval_no: str = ""
    message: str = ""


class PaymentGateway:
    pay_type: PayType

    def charge(self, method: PaymentMethod, amount: int, store: Store, order_id: int) -> GatewayResult:
        raise NotImplementedError

    def cancel(self, approval_no: str, amount: int) -> GatewayResult:
        return GatewayResult(True, approval_no, "취소 완료(mock)")

    @staticmethod
    def _approve(prefix: str) -> GatewayResult:
        return GatewayResult(True, f"{prefix}-{secrets.token_hex(5).upper()}", "승인")


class MockCardGateway(PaymentGateway):
    """데모 규칙: 카드번호 끝자리가 0000 이면 한도초과로 거절 → 다음 우선순위로 넘어가는 흐름 시연용."""

    def __init__(self, pay_type: PayType, prefix: str):
        self.pay_type = pay_type
        self.prefix = prefix

    def charge(self, method, amount, store, order_id):
        if method.masked_number.endswith("0000"):
            return GatewayResult(False, message="한도 초과로 거절되었습니다.")
        return self._approve(self.prefix)


class MockBalanceGateway(PaymentGateway):
    """잔액 기반 결제수단(페이머니, 상품권). mock_balance 로 잔액을 흉내냅니다."""

    def __init__(self, pay_type: PayType, prefix: str):
        self.pay_type = pay_type
        self.prefix = prefix

    def charge(self, method, amount, store, order_id):
        if method.mock_balance is not None:
            if method.mock_balance < amount:
                return GatewayResult(False, message=f"잔액 부족 (잔액 {method.mock_balance:,}원)")
            method.mock_balance -= amount
        return self._approve(self.prefix)


class LocalCurrencyGateway(MockBalanceGateway):
    """지역화폐: 가게 지역과 화폐 발행 지역이 같아야 사용 가능."""

    def charge(self, method, amount, store, order_id):
        if method.region and store.region and method.region != store.region:
            return GatewayResult(False, message=f"{method.region} 지역화폐는 {store.region} 가게에서 쓸 수 없습니다.")
        return super().charge(method, amount, store, order_id)


GATEWAYS: dict[str, PaymentGateway] = {
    PayType.CREDIT_CARD.value: MockCardGateway(PayType.CREDIT_CARD, "CC"),
    PayType.CHECK_CARD.value: MockCardGateway(PayType.CHECK_CARD, "CK"),
    PayType.SAMSUNG_PAY.value: MockCardGateway(PayType.SAMSUNG_PAY, "SP"),
    PayType.KAKAO_PAY.value: MockBalanceGateway(PayType.KAKAO_PAY, "KP"),
    PayType.NAVER_PAY.value: MockBalanceGateway(PayType.NAVER_PAY, "NP"),
    PayType.LOCAL_CURRENCY.value: LocalCurrencyGateway(PayType.LOCAL_CURRENCY, "LC"),
    PayType.ONNURI.value: MockBalanceGateway(PayType.ONNURI, "ON"),
}


def get_gateway(pay_type: str) -> PaymentGateway:
    return GATEWAYS[pay_type]
