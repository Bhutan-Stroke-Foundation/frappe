# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE


from datetime import date, datetime
import json

import frappe
from frappe import _
from frappe.contacts.doctype.contact.contact import get_default_contact
from frappe.desk.doctype.notification_settings.notification_settings import (
	is_email_notifications_enabled_for_type,
)
from frappe.desk.reportview import get_filters_cond
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	date_diff,
	format_datetime,
	get_fullname,
	getdate,
	now_datetime,
	nowdate,
)
from frappe.utils.user import get_enabled_system_users

weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
communication_mapping = {
	"": "Event",
	"Event": "Event",
	"Meeting": "Meeting",
	"Call": "Phone",
	"Sent/Received Email": "Email",
	"Other": "Other",
}

from typing import TYPE_CHECKING, Optional, TypeAlias

if TYPE_CHECKING:
	from frappe.core.doctype.communication.communication import Communication


class Event(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.desk.doctype.event_participants.event_participants import EventParticipants
		from frappe.types import DF

		add_video_conferencing: DF.Check
		all_day: DF.Check
		color: DF.Color | None
		description: DF.TextEditor | None
		ends_on: DF.Datetime | None
		event_category: DF.Literal["Event", "Meeting", "Call", "Sent/Received Email", "Other"]
		event_participants: DF.Table[EventParticipants]
		event_type: DF.Literal["Private", "Public"]
		friday: DF.Check
		google_calendar: DF.Link | None
		google_calendar_event_id: DF.Data | None
		google_calendar_id: DF.Data | None
		google_meet_link: DF.Data | None
		monday: DF.Check
		pulled_from_google_calendar: DF.Check
		repeat_on: DF.Literal["", "Daily", "Weekly", "Monthly", "Yearly"]
		repeat_this_event: DF.Check
		repeat_till: DF.Date | None
		saturday: DF.Check
		send_reminder: DF.Check
		sender: DF.Data | None
		starts_on: DF.Datetime
		status: DF.Literal["Open", "Completed", "Closed", "Cancelled"]
		subject: DF.SmallText
		sunday: DF.Check
		sync_with_google_calendar: DF.Check
		thursday: DF.Check
		tuesday: DF.Check
		wednesday: DF.Check

	# end: auto-generated types
	def validate(self):
		if not self.starts_on:
			self.starts_on = now_datetime()

		# if start == end this scenario doesn't make sense i.e. it starts and ends at the same second!
		self.ends_on = None if self.starts_on == self.ends_on else self.ends_on

		if self.starts_on and self.ends_on:
			self.validate_from_to_dates("starts_on", "ends_on")

		if self.repeat_on == "Daily" and self.ends_on and getdate(self.starts_on) != getdate(self.ends_on):
			frappe.throw(_("Daily Events should finish on the Same Day."))

		if self.sync_with_google_calendar and not self.google_calendar:
			frappe.throw(_("Select Google Calendar to which event should be synced."))

		if not self.sync_with_google_calendar:
			self.add_video_conferencing = 0

	def before_save(self):
		self.set_participants_email()

	def on_update(self):
		self.sync_communication()

	def on_trash(self):
		communications = frappe.get_all(
			"Communication",
			filters={"reference_doctype": self.doctype, "reference_name": self.name},
			pluck="name",
		)
		for communication in communications:
			frappe.delete_doc("Communication", communication, force=True)

	def sync_communication(self):
		if not self.event_participants:
			return

		for participant in self.event_participants:
			if communications := frappe.get_all(
				"Communication",
				filters=[
					["Communication", "reference_doctype", "=", self.doctype],
					["Communication", "reference_name", "=", self.name],
					["Communication Link", "link_doctype", "=", participant.reference_doctype],
					["Communication Link", "link_name", "=", participant.reference_docname],
				],
				pluck="name",
				distinct=True,
			):
				for comm in communications:
					communication = frappe.get_doc("Communication", comm)
					self.update_communication(participant, communication)
			else:
				meta = frappe.get_meta(participant.reference_doctype)
				if hasattr(meta, "allow_events_in_timeline") and meta.allow_events_in_timeline == 1:
					self.create_communication(participant)

	def create_communication(self, participant: "EventParticipants"):
		communication = frappe.new_doc("Communication")
		self.update_communication(participant, communication)
		self.communication = communication.name

	def update_communication(self, participant: "EventParticipants", communication: "Communication"):
		communication.communication_medium = "Event"
		communication.subject = self.subject
		communication.content = self.description if self.description else self.subject
		communication.communication_date = self.starts_on
		communication.sender = self.owner
		communication.sender_full_name = get_fullname(self.owner)
		communication.reference_doctype = self.doctype
		communication.reference_name = self.name
		communication.communication_medium = (
			communication_mapping.get(self.event_category) if self.event_category else ""
		)
		communication.status = "Linked"
		communication.add_link(participant.reference_doctype, participant.reference_docname)
		communication.save(ignore_permissions=True)

	def add_participant(self, doctype, docname):
		"""Add a single participant to event participants

		Args:
		        doctype (string): Reference Doctype
		        docname (string): Reference Docname
		"""
		self.append(
			"event_participants",
			{
				"reference_doctype": doctype,
				"reference_docname": docname,
			},
		)

	def add_participants(self, participants):
		"""Add participant entry

		Args:
		        participants ([Array]): Array of a dict with doctype and docname
		"""
		for participant in participants:
			self.add_participant(participant["doctype"], participant["docname"])

	def set_participants_email(self):
		for participant in self.event_participants:
			if participant.email:
				continue

			if participant.reference_doctype != "Contact":
				participant_contact = get_default_contact(
					participant.reference_doctype, participant.reference_docname
				)
			else:
				participant_contact = participant.reference_docname

			participant.email = (
				frappe.get_value("Contact", participant_contact, "email_id") if participant_contact else None
			)


@frappe.whitelist()
def delete_communication(event, reference_doctype, reference_docname):
	if isinstance(event, str):
		event = json.loads(event)

	deleted_participant = frappe.get_doc(reference_doctype, reference_docname)

	comms = frappe.get_list(
		"Communication",
		filters=[
			["Communication", "reference_doctype", "=", event.get("doctype")],
			["Communication", "reference_name", "=", event.get("name")],
			["Communication Link", "link_doctype", "=", deleted_participant.reference_doctype],
			["Communication Link", "link_name", "=", deleted_participant.reference_docname],
		],
		pluck="name",
	)

	for comm in comms:
		frappe.delete_doc("Communication", comm)


def get_permission_query_conditions(user):
	if not user:
		user = frappe.session.user
	return f"""(`tabEvent`.`event_type`='Public' or `tabEvent`.`owner`={frappe.db.escape(user)})"""


def has_permission(doc, user):
	if doc.event_type == "Public" or doc.owner == user:
		return True

	return False


def send_event_digest():
	today = nowdate()

	# select only those users that have event reminder email notifications enabled
	users = [
		user
		for user in get_enabled_system_users()
		if is_email_notifications_enabled_for_type(user.name, "Event Reminders")
	]

	for user in users:
		events = get_events(today, today, user.name, for_reminder=True)
		if events:
			frappe.set_user_lang(user.name, user.language)

			for e in events:
				e.starts_on = format_datetime(e.starts_on, "hh:mm a")
				if e.all_day:
					e.starts_on = "All Day"

			frappe.sendmail(
				recipients=user.email,
				subject=frappe._("Upcoming Events for Today"),
				template="upcoming_events",
				args={
					"events": events,
				},
				header=[frappe._("Events in Today's Calendar"), "blue"],
			)


@frappe.whitelist()
def get_events(
	start: date, end: date, user: Optional[str] = None, for_reminder: bool = False, filters=None
) -> list[frappe._dict]:
	user = user or frappe.session.user
	EventLikeDict: TypeAlias = Event | frappe._dict

	if isinstance(filters, str):
		filters = json.loads(filters)

	filter_condition = get_filters_cond("Event", filters, [])

	tables = ["`tabEvent`"]
	if "`tabEvent Participants`" in filter_condition:
		tables.append("`tabEvent Participants`")

	event_candidates: list[EventLikeDict] = frappe.db.sql(
		"""
		SELECT `tabEvent`.name,
				`tabEvent`.subject,
				`tabEvent`.description,
				`tabEvent`.color,
				`tabEvent`.starts_on,
				`tabEvent`.ends_on,
				`tabEvent`.owner,
				`tabEvent`.all_day,
				`tabEvent`.event_type,
				`tabEvent`.repeat_this_event,
				`tabEvent`.repeat_on,
				`tabEvent`.repeat_till,
				`tabEvent`.monday,
				`tabEvent`.tuesday,
				`tabEvent`.wednesday,
				`tabEvent`.thursday,
				`tabEvent`.friday,
				`tabEvent`.saturday,
				`tabEvent`.sunday
		FROM {tables}
		WHERE (
				(
					(date(`tabEvent`.starts_on) BETWEEN date(%(start)s) AND date(%(end)s))
					OR (date(`tabEvent`.ends_on) BETWEEN date(%(start)s) AND date(%(end)s))
					OR (
						date(`tabEvent`.starts_on) <= date(%(start)s)
						AND date(`tabEvent`.ends_on) >= date(%(end)s)
					)
				)
				OR (
					date(`tabEvent`.starts_on) <= date(%(start)s)
					AND `tabEvent`.repeat_this_event=1
					AND coalesce(`tabEvent`.repeat_till, '3000-01-01') > date(%(start)s)
				)
			)
		{reminder_condition}
		{filter_condition}
		AND (
				`tabEvent`.event_type='Public'
				OR `tabEvent`.owner=%(user)s
				OR EXISTS(
					SELECT `tabDocShare`.name
					FROM `tabDocShare`
					WHERE `tabDocShare`.share_doctype='Event'
						AND `tabDocShare`.share_name=`tabEvent`.name
						AND `tabDocShare`.user=%(user)s
				)
			)
		AND `tabEvent`.status='Open'
		ORDER BY `tabEvent`.starts_on""".format(
			tables=", ".join(tables),
			filter_condition=filter_condition,
			reminder_condition="AND coalesce(`tabEvent`.send_reminder, 0)=1" if for_reminder else "",
		),
		{
			"start": start,
			"end": end,
			"user": user,
		},
		as_dict=True,
	)

	add_events = []
	remove_events = []

	def add_event(e: EventLikeDict, d: "date"):
		new_event = e.copy()
		new_event.starts_on = datetime.combine(d, e.starts_on.time())

		if e.ends_on:
			end_date = add_days(d, date_diff(e.ends_on, e.starts_on)) if (e.starts_on and e.ends_on) else d
			new_event.ends_on = datetime.combine(end_date, e.ends_on.time())

		add_events.append(new_event)

	for e in event_candidates:
		if not e.repeat_this_event:
			continue

		event_start = e.starts_on.date()
		repeat_till = getdate(e.repeat_till or "3000-01-01")

		def within_range(d):
			return d >= getdate(start) and d <= getdate(end) and d <= repeat_till

		if e.repeat_on == "Yearly":
			for year in range(start.year, end.year + 1):
				d = date(year, event_start.month, event_start.day)
				if within_range(d):
					add_event(e, d)
			remove_events.append(e)

		elif e.repeat_on == "Monthly":
			start_date = date(start.year, start.month, event_start.day)
			for i in range((date_diff(end, start) // 30) + 3):
				d = add_months(start_date, i)
				if within_range(d):
					add_event(e, d)
			remove_events.append(e)

		elif e.repeat_on == "Weekly":
			for cnt in range(date_diff(end, start) + 1):
				d = add_days(start, cnt)
				if e[weekdays[d.weekday()]] and within_range(d):
					add_event(e, d)
			remove_events.append(e)

		elif e.repeat_on == "Daily":
			for cnt in range(date_diff(end, start) + 1):
				d = add_days(start, cnt)
				if within_range(d):
					add_event(e, d)
			remove_events.append(e)

	# Remove events that are not in the range and boolean weekdays fields
	return [
		{fieldname: fieldvalue for fieldname, fieldvalue in event.items() if fieldname not in weekdays}
		for event in event_candidates + add_events
		if event not in remove_events
	]


def delete_events(ref_type, ref_name, delete_event=False):
	participations = frappe.get_all(
		"Event Participants",
		filters={"reference_doctype": ref_type, "reference_docname": ref_name, "parenttype": "Event"},
		fields=["parent", "name"],
	)

	if participations:
		for participation in participations:
			if delete_event:
				frappe.delete_doc("Event", participation.parent, for_reload=True)
			else:
				total_participants = frappe.get_all(
					"Event Participants", filters={"parenttype": "Event", "parent": participation.parent}
				)

				if len(total_participants) <= 1:
					frappe.db.delete("Event", {"name": participation.parent})
					frappe.db.delete("Event Participants", {"name": participation.name})


# Close events if ends_on or repeat_till is less than now_datetime
def set_status_of_events():
	events = frappe.get_list("Event", filters={"status": "Open"}, fields=["name", "ends_on", "repeat_till"])
	for event in events:
		if (event.ends_on and getdate(event.ends_on) < getdate(nowdate())) or (
			event.repeat_till and getdate(event.repeat_till) < getdate(nowdate())
		):
			frappe.db.set_value("Event", event.name, "status", "Closed")
