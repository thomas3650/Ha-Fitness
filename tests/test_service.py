"""Tests for the ha_fitness.skip service: the REST call to the add-on and the errors."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.loader import async_get_integration
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import FakeAddon


async def _skip(hass: HomeAssistant, training_day_id: int = 12) -> None:
    await hass.services.async_call(
        DOMAIN, "skip", {"training_day_id": training_day_id}, blocking=True
    )


@pytest.mark.usefixtures("cards_bundle")
async def test_skip_service_ok_and_user_agent(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """The service posts the skip to the add-on, as ha_fitness/<integration version>."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    version = (await async_get_integration(hass, DOMAIN)).version

    await _skip(hass, 12)

    assert fake_addon.skip_user_agents == [f"ha_fitness/{version}"]
    assert fake_addon.skip_ids == [12]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
@pytest.mark.parametrize(
    ("status", "error", "key"),
    [
        (404, ServiceValidationError, "not_found"),
        (409, ServiceValidationError, "not_open"),
        (500, HomeAssistantError, "unavailable"),
    ],
)
async def test_skip_service_not_found_not_open_unavailable(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    status: int,
    error: type[HomeAssistantError],
    key: str,
) -> None:
    """A 404 is not_found and a 409 not_open (validation errors); another status is unavailable."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    fake_addon.skip_status = status

    with pytest.raises(error) as raised:
        await _skip(hass, 99)

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == key
    if key == "unavailable":
        assert not isinstance(raised.value, ServiceValidationError)
    assert len(fake_addon.skip_user_agents) == 1
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_skip_service_unavailable_without_loaded_entry(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """With the entry unloaded, the service still exists and raises unavailable."""
    await set_up(hass, config_entry)
    await unload(hass, config_entry)

    with pytest.raises(HomeAssistantError) as raised:
        await _skip(hass)

    assert raised.value.translation_key == "unavailable"
    assert fake_addon.skip_user_agents == []


@pytest.mark.usefixtures("cards_bundle", "socket_enabled")
async def test_skip_service_unavailable_when_addon_unreachable(
    hass: HomeAssistant, unused_tcp_port: int
) -> None:
    """With nothing listening at the add-on's URL, the service raises unavailable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Fitness",
        data={"url": f"http://127.0.0.1:{unused_tcp_port}"},
        unique_id="ha_fitness",
        version=2,
    )
    entry.add_to_hass(hass)
    await set_up(hass, entry)

    with pytest.raises(HomeAssistantError) as raised:
        await _skip(hass)

    assert raised.value.translation_key == "unavailable"
    assert not isinstance(raised.value, ServiceValidationError)
    await unload(hass, entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_skip_service_refuses_id_0(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """Training day ids start at 1, as in services.yaml: 0 is refused before any request."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    with pytest.raises(probatio.Invalid):
        await _skip(hass, 0)

    assert fake_addon.skip_ids == []
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
@pytest.mark.parametrize("case", ["unsupported", "no_hello"])
async def test_skip_service_unavailable_while_addon_not_usable(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    case: str,
) -> None:
    """On an unsupported API version, or before a hello, the service raises unavailable and posts nothing."""
    if case == "unsupported":
        fake_addon.api_version = 3
    else:
        fake_addon.send_hello = False
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: fake_addon.connects == 1)

    with pytest.raises(HomeAssistantError) as raised:
        await _skip(hass)

    assert raised.value.translation_key == "unavailable"
    assert fake_addon.skip_ids == []
    await unload(hass, config_entry)
