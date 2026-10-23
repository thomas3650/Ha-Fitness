"""The people who train, each linked to an HA person (spec §4)."""

import builtins
from collections import Counter

from sqlalchemy import Engine, select

from . import changes
from .db import session
from .errors import Invalid, Unavailable
from .ha import HaClient
from .models import Person as PersonRow
from .schemas import NewPerson, PeopleView, Person

MAX_PEOPLE = 2


def _person(row: PersonRow) -> Person:
    """Turn a row into a `Person`."""
    return Person(id=row.id, name=row.name, person_entity_id=row.person_entity_id)


class People:
    """Lists and sets the people; HA is asked for its persons."""

    def __init__(self, engine: Engine, ha: HaClient) -> None:
        """Use `engine` for the people and `ha` for the HA persons."""
        self._engine = engine
        self._ha = ha

    def stored(self) -> builtins.list[Person]:
        """Return the stored people in colour order, without asking HA."""
        with session(self._engine) as db_session:
            rows = db_session.scalars(select(PersonRow).order_by(PersonRow.position))
            return [_person(row) for row in rows]

    def list(self) -> PeopleView:
        """Return the people and HA's persons; when HA can't be read, `ha_persons` is null and `ha_error` says why."""
        people = self.stored()
        try:
            ha_persons = self._ha.persons()
        except Unavailable as error:
            return PeopleView(people=people, ha_persons=None, ha_error=str(error))
        return PeopleView(people=people, ha_persons=ha_persons, ha_error=None)

    def set(
        self, people: builtins.list[NewPerson], client: str
    ) -> builtins.list[Person]:
        """Replace the people; a person whose entity id stays keeps their id.

        Raise `Invalid` for more than two people, a shared entity id or an entity that isn't an HA person, and
        `Unavailable` when HA can't be asked.
        """
        if len(people) > MAX_PEOPLE:
            raise Invalid(f"At most {MAX_PEOPLE} people, got {len(people)}")
        counts = Counter(person.person_entity_id for person in people)
        shared = [entity_id for entity_id, count in counts.items() if count > 1]
        if shared:
            raise Invalid(f"'{shared[0]}' is given for more than one person")
        ha_persons = self._ha.persons()
        known = {ha_person.entity_id for ha_person in ha_persons}
        for person in people:
            if person.person_entity_id not in known:
                raise Invalid(
                    {
                        "message": f"'{person.person_entity_id}' isn't a person in Home Assistant",
                        "entity_id": person.person_entity_id,
                        "ha_persons": [
                            ha_person.model_dump() for ha_person in ha_persons
                        ],
                    }
                )
        with session(self._engine) as db_session:
            rows = {
                row.person_entity_id: row
                for row in db_session.scalars(select(PersonRow))
            }
            for entity_id, row in rows.items():
                if entity_id not in counts:
                    db_session.delete(row)
            db_session.flush()
            kept: list[PersonRow] = []
            for position, person in enumerate(people):
                row = rows.get(person.person_entity_id) or PersonRow(
                    person_entity_id=person.person_entity_id
                )
                row.name = person.name
                row.position = position
                db_session.add(row)
                kept.append(row)
            db_session.flush()
            names = ", ".join(person.name for person in people) or "none"
            changes.record(
                db_session,
                client=client,
                action="people.set",
                target="people",
                summary=f"Set people: {names}",
            )
            return [_person(row) for row in kept]
